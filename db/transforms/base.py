from abc import ABC, abstractmethod
from copy import deepcopy
import itertools

import sqlalchemy
from sqlalchemy import select

from db.functions.operations import apply
from db.functions.operations.deserialize import get_db_function_subclass_by_id
from db.records.operations import group, relevance, sort as rec_sort


class Transform(ABC):
    type = None
    spec = None

    def __init__(
            self,
            spec,
    ):
        if self.type is None:
            raise ValueError(
                'Transform subclasses must define a type.'
            )
        if spec is None:
            raise ValueError(
                'A spec must be passed when instantiating a Transform subclass.'
            )
        self.spec = spec

    @abstractmethod
    def apply_to_relation(self, relation):
        return None

    def __eq__(self, other):
        return (
            type(self) is type(other)
            and self.__dict__ == other.__dict__
        )

    @property
    def map_of_output_alias_to_input_alias(self):
        """
        Expected to return a mapping of output aliases to input aliases.

        Useful when looking for parent aliases of a given alias.

        Notice that the reverse mapping (from input aliases to output aliases) would be
        significantly different, because a single input alias can map to multiple output aliases.
        """
        return dict()


class Filter(Transform):
    type = "filter"

    def apply_to_relation(self, relation):
        filter = self.spec
        enforce_relation_type_expectations(relation)
        executable = _to_executable(relation)
        if filter is not None:
            executable = apply.apply_db_function_spec_as_filter(executable, filter)
        return _to_non_executable(executable)


class Order(Transform):
    type = "order"

    def apply_to_relation(self, relation):
        order_by = self.spec
        enforce_relation_type_expectations(relation)
        if order_by is not None:
            executable = rec_sort.apply_relation_sorting(relation, order_by)
        else:
            executable = _to_executable(relation)
        return _to_non_executable(executable)


class Limit(Transform):
    type = "limit"

    def apply_to_relation(self, relation):
        limit = self.spec
        executable = _to_executable(relation)
        executable = executable.limit(limit)
        return _to_non_executable(executable)


class Offset(Transform):
    type = "offset"

    def apply_to_relation(self, relation):
        offset = self.spec
        executable = _to_executable(relation)
        executable = executable.offset(offset)
        return _to_non_executable(executable)


class DuplicateOnly(Transform):
    type = "duplicate_only"

    def apply_to_relation(self, relation):
        duplicate_columns = self.spec
        enforce_relation_type_expectations(relation)
        DUPLICATE_LABEL = "_is_dupe"
        duplicate_flag_col = (
            sqlalchemy.func
            .count(1)
            .over(partition_by=duplicate_columns) > 1
        ).label(DUPLICATE_LABEL)
        duplicate_flag_cte = (
            select(
                *relation.c,
                duplicate_flag_col,
            ).select_from(relation)
        ).cte()
        executable = (
            select(duplicate_flag_cte)
            .where(duplicate_flag_cte.c[DUPLICATE_LABEL])
        )
        return _to_non_executable(executable)


class Search(Transform):
    type = "search"
    spec = []

    @property
    def search_spec(self):
        return self.spec[0]

    @property
    def limit_spec(self):
        return self.spec[1]

    def apply_to_relation(self, relation):
        search = self.search_spec
        limit = self.limit_spec
        search_params = {search_obj['column']: search_obj['literal'] for search_obj in search}
        executable = relevance.get_rank_and_filter_rows_query(relation, search_params, limit)
        return _to_non_executable(executable)


class Group(Transform):
    type = "group"

    def apply_to_relation(self, relation):
        group_by = self.spec
        # TODO maybe keep this as json, and convert to GroupBy at last moment?
        # other transform specs are json at this point in the pipeline
        if isinstance(group_by, group.GroupBy):
            executable = group.get_group_augmented_records_pg_query(relation, group_by)
            return _to_non_executable(executable)
        else:
            return relation


class Summarize(Transform):
    """
    "spec": {
        "base_grouping_column": "col1",
        "grouping_expressions": [
            {
                "input_alias": "col1",
                "output_alias": "col1_alias",
                "preproc": None  # optional for grouping cols
            },
            {
                "input_alias": "col2",
                "output_alias": None,  # optional for grouping cols
                "preproc": "truncate_to_month"  # optional DBFunction id
            },
        ],
        "aggregation_expressions": [
            {
                "input_alias": "col3",
                "output_alias": "col3_alias",  # required for aggregation cols
                "function": "aggregate_to_array"  # required DBFunction id
            }
        ]
    }
    """
    type = "summarize"

    # When generating specs, largely in testing, we want predictable output aliases.
    default_group_output_alias_suffix = "_grouped"
    default_agg_output_alias_suffix = "_agged"

    @property
    def map_of_output_alias_to_input_alias(self):
        m = dict()
        grouping_expressions = self.spec['grouping_expressions']
        aggregation_expressions = self.spec['aggregation_expressions']
        all_expressions = grouping_expressions + aggregation_expressions
        for expression in all_expressions:
            expr_output_alias = expression.get('output_alias', None)
            expr_input_alias = expression.get('input_alias', None)
            m[expr_output_alias] = expr_input_alias
        return m

    def apply_to_relation(self, relation):

        def _get_grouping_column(col_spec):
            preproc = col_spec.get('preproc')
            out_alias = col_spec.get('output_alias')
            in_alias = col_spec['input_alias']

            expr = relation.columns[in_alias]

            if preproc is not None:
                expr = get_db_function_subclass_by_id(preproc).to_sa_expression(expr)
            if out_alias is not None:
                expr = expr.label(out_alias)

            return expr

        grouping_expressions = [
            _get_grouping_column(col_spec)
            for col_spec in self._grouping_col_specs
        ]
        aggregation_expressions = [
            (
                get_db_function_subclass_by_id(col_spec['function'])
                .to_sa_expression(relation.columns[col_spec['input_alias']])
                .label(col_spec['output_alias'])
            )
            for col_spec in self._aggregation_col_specs
        ]

        executable = (
            select(*grouping_expressions, *aggregation_expressions)
            .group_by(*grouping_expressions)
        )
        return _to_non_executable(executable)

    def get_new_with_aliases_added_to_group_by(self, aliases):
        def get_col_spec_from_alias(alias):
            return dict(
                input_alias=alias,
                output_alias=alias + default_suffix,
            )
        spec_field = 'grouping_expressions'
        default_suffix = self.default_group_output_alias_suffix
        return _add_aliases_to_summarization_expr_field(
            summarization=self,
            spec_field=spec_field,
            aliases=aliases,
            get_col_spec_from_alias=get_col_spec_from_alias,
        )

    def get_new_with_aliases_added_to_agg_on(self, aliases):
        def get_col_spec_from_alias(alias):
            return dict(
                input_alias=alias,
                output_alias=alias + default_suffix,
                function=default_aggregation_fn
            )
        spec_field = 'aggregation_expressions'
        default_suffix = self.default_agg_output_alias_suffix
        default_aggregation_fn = 'aggregate_to_array'
        return _add_aliases_to_summarization_expr_field(
            summarization=self,
            spec_field=spec_field,
            aliases=aliases,
            get_col_spec_from_alias=get_col_spec_from_alias,
        )

    @property
    def base_grouping_column(self):
        return self.spec['base_grouping_column']

    @property
    def grouping_input_aliases(self):
        return [
            col_spec['input_alias']
            for col_spec
            in self._grouping_col_specs
        ]

    @property
    def aggregation_input_aliases(self):
        return [
            col_spec['input_alias']
            for col_spec
            in self._aggregation_col_specs
        ]

    @property
    def _grouping_col_specs(self):
        return self.spec.get("grouping_expressions", [])

    @property
    def _aggregation_col_specs(self):
        return self.spec.get("aggregation_expressions", [])


def _add_aliases_to_summarization_expr_field(
    summarization, spec_field, aliases, get_col_spec_from_alias
):
    """
    Returns new summarization with aliases added to `spec_field`.

    This function will apply `get_col_spec_from_alias` to each column alias in `aliases`,
    and add the results to the chosen `spec_field` in a copy of `summarization`, returning the copy.
    """
    summarization = deepcopy(summarization)
    expressions_to_add = [
        get_col_spec_from_alias(alias)
        for alias
        in aliases
    ]
    existing_expressions = summarization.spec.get(spec_field, [])
    new_expressions = list(
        itertools.chain(
            existing_expressions, expressions_to_add
        )
    )
    summarization.spec[spec_field] = new_expressions
    return summarization


class SelectSubsetOfColumns(Transform):
    type = "select"

    def apply_to_relation(self, relation):
        columns_to_select = self.spec
        if columns_to_select:
            processed_columns_to_select = [
                _make_sure_column_expression(column)
                for column
                in columns_to_select
            ]
            executable = select(*processed_columns_to_select).select_from(relation)
            return _to_non_executable(executable)
        else:
            return relation


def _make_sure_column_expression(input):
    if isinstance(input, str):
        return sqlalchemy.column(input)
    else:
        return input


def _to_executable(relation):
    """
    Executables are a subset of Selectables.
    """
    assert isinstance(relation, sqlalchemy.sql.expression.Selectable)
    if isinstance(relation, sqlalchemy.sql.expression.Executable):
        return relation
    else:
        return select(relation)


def _to_non_executable(relation):
    """
    Non-executables are Selectables that are not Executables. Non-executables are more portable
    than Executables.
    """
    assert isinstance(relation, sqlalchemy.sql.expression.Selectable)
    if isinstance(relation, sqlalchemy.sql.expression.Executable):
        return relation.cte()
    else:
        return relation


def enforce_relation_type_expectations(relation):
    """
    The convention being enforced is to pass around instances of Selectables that are not
    Executables. We need to do it one way, for the sake of uniformity and compatibility.
    It's not the other way around, because if you pass around Executables, composition sometimes
    works differently.

    This method is a development tool mostly, probably shouldn't exist in actual production.
    """
    assert isinstance(relation, sqlalchemy.sql.expression.Selectable)
    assert not isinstance(relation, sqlalchemy.sql.expression.Executable)
