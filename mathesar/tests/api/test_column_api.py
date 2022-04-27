import json

import pytest
from unittest.mock import patch
from django.core.cache import cache

from sqlalchemy import select
from db.columns.operations.alter import alter_column_type
from mathesar import models
from mathesar.api.exceptions.error_codes import ErrorCodes
from mathesar.tests.api.test_table_api import check_columns_response
from db.constants import COLUMN_NAME_TEMPLATE
from db.types.base import PostgresType, MathesarCustomType


def _get_columns_by_name(table, name_list):
    columns_by_name_dict = {
        col.name: col for col in models.Column.objects.filter(table=table) if col.name in name_list
    }
    return [columns_by_name_dict[col_name] for col_name in name_list]


def test_column_list(column_test_table, client):
    cache.clear()
    response = client.get(f"/api/db/v0/tables/{column_test_table.id}/columns/")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data['count'] == len(column_test_table.sa_columns)
    expect_results = [
        {
            'name': 'mycolumn0',
            'type': PostgresType.INTEGER.id,
            'type_options': None,
            'nullable': False,
            'primary_key': True,
            'display_options': None,
            'default': {
                'value': """nextval('"Patents".anewtable_mycolumn0_seq'::regclass)""",
                'is_dynamic': True
            },
            'valid_target_types': [
                'bigint', 'boolean', 'character', 'character varying',
                'double precision', 'integer', 'mathesar_types.mathesar_money',
                'mathesar_types.multicurrency_money', 'money', 'numeric',
                'real', 'smallint', 'text',
            ],
        },
        {
            'name': 'mycolumn1',
            'type': PostgresType.INTEGER.id,
            'type_options': None,
            'nullable': False,
            'primary_key': False,
            'display_options': None,
            'default': None,
            'valid_target_types': [
                'bigint', 'boolean', 'character', 'character varying',
                'double precision', 'integer', 'mathesar_types.mathesar_money',
                'mathesar_types.multicurrency_money', 'money', 'numeric',
                'real', 'smallint', 'text',
            ],
        },
        {
            'name': 'mycolumn2',
            'type': PostgresType.INTEGER.id,
            'type_options': None,
            'nullable': True,
            'primary_key': False,
            'display_options': None,
            'default': {
                'value': 5,
                'is_dynamic': False,
            },
            'valid_target_types': [
                'bigint', 'boolean', 'character', 'character varying',
                'double precision', 'integer', 'mathesar_types.mathesar_money',
                'mathesar_types.multicurrency_money', 'money', 'numeric',
                'real', 'smallint', 'text',
            ],
        },
        {
            'name': 'mycolumn3',
            'type': PostgresType.CHARACTER_VARYING.id,
            'type_options': None,
            'nullable': True,
            'primary_key': False,
            'display_options': None,
            'valid_target_types': [
                'bigint', 'boolean', 'character', 'character varying', 'date',
                'double precision', 'integer', 'interval',
                'mathesar_types.email', 'mathesar_types.mathesar_money',
                'mathesar_types.multicurrency_money', 'mathesar_types.uri',
                'money', 'numeric', 'real', 'smallint', 'text',
                'time with time zone', 'time without time zone',
                'timestamp with time zone', 'timestamp without time zone',
            ],
            'default': None,
        }
    ]
    check_columns_response(response_data['results'], expect_results)


def test_column_create(column_test_table, client):
    name = "anewcolumn"
    db_type = PostgresType.NUMERIC
    cache.clear()
    num_columns = len(column_test_table.sa_columns)
    data = {
        "name": name,
        "type": db_type.id,
        "display_options": {"show_as_percentage": True},
        "nullable": False
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/",
        data=data,
    )
    assert response.status_code == 201
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    assert new_columns_response.json()["count"] == num_columns + 1
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["name"] == name
    assert actual_new_col["type"] == db_type.id
    assert actual_new_col["default"] is None


create_default_test_list = [
    (PostgresType.BOOLEAN, True, True, True),
    (PostgresType.INTERVAL, "00:42:00", "P0Y0M0DT0H42M0S", "P0Y0M0DT0H42M0S"),
    (PostgresType.NUMERIC, 42, 42, 42),
    (PostgresType.CHARACTER_VARYING, "test_string", "test_string", "test_string"),
    (PostgresType.DATE, "2020-1-1", "2020-01-01 AD", "2020-01-01 AD"),
    (MathesarCustomType.EMAIL, "test@test.com", "test@test.com", "test@test.com"),
]


@pytest.mark.parametrize(
    "db_type,default,default_obj,expt_default", create_default_test_list
)
def test_column_create_default(
        column_test_table, db_type, default, default_obj, expt_default, client, engine
):
    cache.clear()
    name = "anewcolumn"
    data = {"name": name, "type": db_type.id, "default": {"value": default}}
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/",
        json.dumps(data), content_type='application/json'
    )
    assert response.status_code == 201

    # Ensure the correct serialized date is returned by the API
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["default"]["value"] == expt_default

    # Ensure the correct date value is generated when inserting a new record
    sa_table = column_test_table._sa_table
    with engine.begin() as conn:
        conn.execute(sa_table.insert((1, 1, 1, 'str')))
        created_default = conn.execute(select(sa_table)).fetchall()[0][-1]
    assert created_default == default_obj


def test_column_create_invalid_default(column_test_table, client):
    cache.clear()
    name = "anewcolumn"
    data = {
        "name": name,
        "type": PostgresType.BOOLEAN.id,
        "default": {"value": "Not a boolean"},
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/",
        json.dumps(data),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert f'default "{data["default"]}" is invalid for type' in response.json()[0]['message']


create_display_options_test_list = [
    (PostgresType.BOOLEAN, {"input": "dropdown"}),
    (PostgresType.BOOLEAN, {"input": "checkbox", "custom_labels": {"TRUE": "yes", "FALSE": "no"}}),
    (PostgresType.DATE, {'format': 'YYYY-MM-DD'}),
    (PostgresType.INTERVAL, {'format': 'DD HH:mm:ss.SSS'}),
    (PostgresType.NUMERIC, {"show_as_percentage": True}),
    (PostgresType.NUMERIC, {"show_as_percentage": True, "locale": "en_US"}),
    (PostgresType.TIMESTAMP_WITH_TIME_ZONE, {'format': 'YYYY-MM-DD hh:mm'}),
    (PostgresType.TIMESTAMP_WITHOUT_TIME_ZONE, {'format': 'YYYY-MM-DD hh:mm'}),
    (PostgresType.TIME_WITHOUT_TIME_ZONE, {'format': 'hh:mm'}),
    (PostgresType.TIME_WITH_TIME_ZONE, {'format': 'hh:mm Z'}),
]


@pytest.mark.parametrize("db_type,display_options", create_display_options_test_list)
def test_column_create_display_options(
    column_test_table, db_type, display_options, client, engine
):
    cache.clear()
    name = "anewcolumn"
    data = {"name": name, "type": db_type.id, "display_options": display_options}
    response = client.post(f"/api/db/v0/tables/{column_test_table.id}/columns/", data)
    assert response.status_code == 201

    # Ensure the correct serialized date is returned by the API
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["display_options"] == display_options


_too_long_string = "x" * 256


create_display_options_invalid_test_list = [
    (PostgresType.BOOLEAN, {"input": "invalid"}),
    (PostgresType.BOOLEAN, {"input": "checkbox", "custom_labels": {"yes": "yes", "1": "no"}}),
    (PostgresType.NUMERIC, {"show_as_percentage": "wrong value type"}),
    (PostgresType.DATE, {'format': _too_long_string}),
    (PostgresType.TIMESTAMP_WITH_TIME_ZONE, {'format': []}),
    (PostgresType.TIMESTAMP_WITHOUT_TIME_ZONE, {'format': _too_long_string}),
    (PostgresType.TIME_WITH_TIME_ZONE, {'format': _too_long_string}),
    (PostgresType.TIME_WITHOUT_TIME_ZONE, {'format': {}}),
]


@pytest.mark.parametrize("db_type,display_options", create_display_options_invalid_test_list)
def test_column_create_wrong_display_options(
    column_test_table, db_type, display_options, client, engine
):
    cache.clear()
    name = "anewcolumn"
    data = {"name": name, "type": db_type.id, "display_options": display_options}
    response = client.post(f"/api/db/v0/tables/{column_test_table.id}/columns/", data)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "db_type,type_options",
    [
        (PostgresType.NUMERIC, {"precision": 5, "scale": 3}),
        (PostgresType.CHARACTER_VARYING, {"length": 5}),
        (PostgresType.CHARACTER, {"length": 5}),
        (PostgresType.INTERVAL, {"precision": 5}),
        (PostgresType.INTERVAL, {"precision": 5, "fields": "second"}),
        (PostgresType.INTERVAL, {"fields": "day"}),
    ]
)
def test_column_create_retrieve_options(column_test_table, client, db_type, type_options):
    name = "anewcolumn"
    cache.clear()
    num_columns = len(column_test_table.sa_columns)
    data = {
        "name": name, "type": db_type.id, "type_options": type_options,
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/",
        data=data,
    )
    assert response.status_code == 201
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    assert new_columns_response.json()["count"] == num_columns + 1
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["name"] == name
    assert actual_new_col["type"] == db_type.id
    assert actual_new_col["type_options"] == type_options


invalid_type_options = [
    {"precision": 5, "scale": 8},
    {"precision": "asd"},
    {"nonoption": 34},
    {"length": "two"},
]


@pytest.mark.parametrize("type_options", invalid_type_options)
def test_column_create_bad_options(column_test_table, client, type_options):
    name = "anewcolumn"
    db_type = PostgresType.NUMERIC
    cache.clear()
    data = {
        "name": name, "type": db_type.id, "type_options": type_options,
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/",
        data=data,
    )
    assert response.status_code == 400


def test_column_create_duplicate(column_test_table, client):
    column = column_test_table.sa_columns[0]
    name = column.name
    db_type = PostgresType.NUMERIC
    cache.clear()
    data = {
        "name": name, "type": db_type.id
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    assert response.status_code == 400


def test_column_create_some_parameters(column_test_table, client):
    data = {
        "name": "only name",
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    response_data = response.json()[0]
    assert response.status_code == 400
    assert response_data['message'] == "This field is required."
    assert response_data['field'] == "type"


def test_column_create_no_name_parameter(column_test_table, client):
    cache.clear()
    db_type = PostgresType.BOOLEAN
    num_columns = len(column_test_table.sa_columns)
    generated_name = f"{COLUMN_NAME_TEMPLATE}{num_columns}"
    data = {
        "type": db_type.id
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    assert response.status_code == 201
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    assert new_columns_response.json()["count"] == num_columns + 1
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["name"] == generated_name
    assert actual_new_col["type"] == db_type.id


def test_column_create_name_parameter_empty(column_test_table, client):
    cache.clear()
    name = ""
    db_type = PostgresType.BOOLEAN
    num_columns = len(column_test_table.sa_columns)
    generated_name = f"{COLUMN_NAME_TEMPLATE}{num_columns}"
    data = {
        "name": name, "type": db_type.id
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    assert response.status_code == 201
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    assert new_columns_response.json()["count"] == num_columns + 1
    actual_new_col = new_columns_response.json()["results"][-1]
    assert actual_new_col["name"] == generated_name
    assert actual_new_col["type"] == db_type.id


def test_column_update_name(column_test_table, client):
    cache.clear()
    name = "updatedname"
    data = {"name": name}
    column = _get_columns_by_name(column_test_table, ['mycolumn1'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.status_code == 200
    assert response.json()["name"] == name
    response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/"
    )
    assert response.status_code == 200
    assert response.json()["name"] == name


def test_column_update_display_options(column_test_table_with_service_layer_options, client):
    cache.clear()
    table, _ = column_test_table_with_service_layer_options
    column_indexes = [2, 3, 4, 5]
    for column_index in column_indexes:
        colum_name = f"mycolumn{column_index}"
        column = _get_columns_by_name(table, [colum_name])[0]
        column_id = column.id
        display_options = {
            "input": "dropdown",
            "custom_labels": {"TRUE": "yes", "FALSE": "no"}
        }
        column_data = {
            'type': PostgresType.BOOLEAN.id,
            'type_options': {},
            'display_options': display_options,
        }
        response = client.patch(
            f"/api/db/v0/tables/{table.id}/columns/{column_id}/",
            column_data,
        )
        assert response.status_code == 200
        assert response.json()["display_options"] == display_options


def test_column_update_type_with_existing_display_options(column_test_table_with_service_layer_options, client):
    cache.clear()
    table, _ = column_test_table_with_service_layer_options
    colum_name = "mycolumn2"
    column = _get_columns_by_name(table, [colum_name])[0]
    column_id = column.id
    column_data = {'type': PostgresType.BOOLEAN.id}
    response = client.patch(
        f"/api/db/v0/tables/{table.id}/columns/{column_id}/",
        column_data,
    )
    assert response.status_code == 200
    assert response.json()["display_options"] is None


def test_column_display_options_type_on_reflection(column_test_table,
                                                   client, engine):
    cache.clear()
    table = column_test_table
    response = client.get(
        f"/api/db/v0/tables/{table.id}/columns/",
    )
    columns = response.json()['results']
    for column in columns:
        assert column["display_options"] is None


def test_column_invalid_display_options_type_on_reflection(column_test_table_with_service_layer_options,
                                                           client, engine):
    cache.clear()
    table, columns = column_test_table_with_service_layer_options
    column_index = 2
    column = columns[column_index]
    with engine.begin() as conn:
        alter_column_type(table.oid, column.name, engine, conn, PostgresType.BOOLEAN)
    column_id = column.id
    response = client.get(
        f"/api/db/v0/tables/{table.id}/columns/{column_id}/",
    )
    assert response.json()["display_options"] is None


def test_column_alter_same_type_display_options(column_test_table_with_service_layer_options,
                                                client, engine):
    cache.clear()
    table, columns = column_test_table_with_service_layer_options
    column_index = 2
    column = columns[column_index]
    pre_alter_display_options = column.display_options
    with engine.begin() as conn:
        alter_column_type(table.oid, column.name, engine, conn, PostgresType.NUMERIC)
    column_id = column.id
    response = client.get(
        f"/api/db/v0/tables/{table.id}/columns/{column_id}/",
    )
    assert response.json()["display_options"] == pre_alter_display_options


def test_column_update_default(column_test_table, client):
    cache.clear()
    expt_default = 5
    data = {"default": {"value": expt_default}}  # Ensure we pass a int and not a str
    column = _get_columns_by_name(column_test_table, ['mycolumn0'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=json.dumps(data),
        content_type="application/json",
    )
    assert response.json()["default"]["value"] == expt_default


def test_column_update_delete_default(column_test_table, client):
    cache.clear()
    expt_default = None
    data = {"default": None}
    column = _get_columns_by_name(column_test_table, ['mycolumn0'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=data,
    )
    assert response.json()["default"] == expt_default


def test_column_update_default_invalid_cast(column_test_table, client):
    cache.clear()
    data = {"default": {"value": "not an integer"}}
    column = _get_columns_by_name(column_test_table, ['mycolumn0'])[0]

    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=json.dumps(data),
        content_type="application/json"
    )
    assert response.status_code == 400


def test_column_update_type_dynamic_default(column_test_table, client):
    cache.clear()
    db_type = PostgresType.NUMERIC
    data = {"type": db_type.id}
    column = _get_columns_by_name(column_test_table, ['mycolumn0'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.status_code == 400


def test_column_update_type(column_test_table, client):
    cache.clear()
    db_type = PostgresType.BOOLEAN
    data = {"type": db_type.id}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.json()["type"] == db_type.id


def test_column_update_name_and_type(column_test_table, client):
    cache.clear()
    db_type = PostgresType.BOOLEAN
    new_name = 'new name'
    data = {"type": db_type.id, "name": new_name}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.json()["type"] == db_type.id
    assert response.json()["name"] == new_name


def test_column_update_name_type_nullable(column_test_table, client):
    cache.clear()
    db_type = PostgresType.BOOLEAN
    new_name = 'new name'
    data = {"type": db_type.id, "name": new_name, "nullable": True}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]

    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.json()["type"] == db_type.id
    assert response.json()["name"] == new_name
    assert response.json()["nullable"] is True


def test_column_update_name_type_nullable_default(column_test_table, client):
    cache.clear()
    db_type = PostgresType.BOOLEAN
    new_name = 'new name'
    data = {
        "type": db_type.id,
        "name": new_name,
        "nullable": True,
        "default": {"value": True},
    }
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=json.dumps(data),
        content_type='application/json'
    )
    assert response.json()["type"] == db_type.id
    assert response.json()["name"] == new_name
    assert response.json()["nullable"] is True
    assert response.json()["default"]["value"] is True


def test_column_update_type_options(column_test_table, client):
    cache.clear()
    db_type = PostgresType.NUMERIC
    type_options = {"precision": 3, "scale": 1}
    data = {"type": db_type.id, "type_options": type_options}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data,
    )
    assert response.json()["type"] == db_type.id
    assert response.json()["type_options"] == type_options


def test_column_update_type_options_no_type(column_test_table, client):
    cache.clear()
    db_type = PostgresType.NUMERIC
    data = {"type": db_type.id}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data,
    )
    type_options = {"precision": 3, "scale": 1}
    type_option_data = {"type_options": type_options}
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        type_option_data,
    )
    assert response.json()["type"] == db_type.id
    assert response.json()["type_options"] == type_options


def test_column_update_invalid_type(create_patents_table, client):
    table = create_patents_table('Column Invalid Type')
    body = {"type": PostgresType.BIGINT.id}
    response = client.get(
        f"/api/db/v0/tables/{table.id}/columns/"
    )
    assert response.status_code == 200
    columns = response.json()['results']
    column_index = 3
    column_id = columns[column_index]['id']
    response = client.patch(
        f"/api/db/v0/tables/{table.id}/columns/{column_id}/",
        body
    )
    assert response.status_code == 400
    response_json = response.json()
    assert response_json[0]['code'] == ErrorCodes.InvalidTypeCast.value
    assert response_json[0]['message'] == "This type casting is invalid."


def test_column_update_returns_table_dependent_fields(column_test_table, client):
    cache.clear()
    expt_default = 5
    data = {"default": {"value": expt_default}}
    column = _get_columns_by_name(column_test_table, ['mycolumn1'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=data,
    )
    assert response.json()["default"] is not None
    assert response.json()["id"] is not None


@pytest.mark.parametrize("type_options", invalid_type_options)
def test_column_update_type_invalid_options(column_test_table, client, type_options):
    cache.clear()
    db_type = PostgresType.NUMERIC
    data = {"type": db_type.id, "type_options": type_options}
    column = _get_columns_by_name(column_test_table, ['mycolumn3'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/",
        data=data,
    )
    assert response.status_code == 400


# This cast is currently succeeding, because the column is empty.
# While we do have the facilities to not recommend a cast like this (and we don't), this test is
# testing whether or not we allow attempting this cast anyway. It is not clear to me (Dom) that we
# should forbid it, and our code currently does not forbid it.
@pytest.mark.skip(reason="unclear whether this is indeed an unsupported cast")
def test_column_update_type_invalid_cast(column_test_table, client):
    cache.clear()
    db_type = MathesarCustomType.EMAIL
    data = {"type": db_type.id}
    column = _get_columns_by_name(column_test_table, ['mycolumn1'])[0]
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/", data=data
    )
    assert response.status_code == 400


def test_column_update_when_missing(column_test_table, client):
    cache.clear()
    name = "updatedname"
    data = {"name": name}
    response = client.patch(
        f"/api/db/v0/tables/{column_test_table.id}/columns/99999/", data=data
    )
    assert response.status_code == 404
    response_data = response.json()[0]
    assert response_data['message'] == "Not found."
    assert response_data['code'] == ErrorCodes.NotFound.value


def test_column_destroy(column_test_table, client):
    cache.clear()
    num_columns = len(column_test_table.sa_columns)
    col_one_name = column_test_table.sa_columns[1].name
    column = _get_columns_by_name(column_test_table, ['mycolumn1'])[0]
    response = client.delete(
        f"/api/db/v0/tables/{column_test_table.id}/columns/{column.id}/"
    )
    assert response.status_code == 204
    new_columns_response = client.get(
        f"/api/db/v0/tables/{column_test_table.id}/columns/"
    )
    new_data = new_columns_response.json()
    assert col_one_name not in [col["name"] for col in new_data["results"]]
    assert new_data["count"] == num_columns - 1


def test_column_destroy_when_missing(column_test_table, client):
    cache.clear()
    response = client.delete(
        f"/api/db/v0/tables/{column_test_table.id}/columns/99999/"
    )
    response_data = response.json()[0]
    assert response_data['message'] == "Not found."
    assert response_data['code'] == ErrorCodes.NotFound.value
    assert response.status_code == 404


def test_column_duplicate(column_test_table, client):
    cache.clear()
    column = _get_columns_by_name(column_test_table, ['mycolumn1'])[0]
    target_col = column_test_table.sa_columns[column.name]
    data = {
        "name": "new_col_name",
        "source_column": column.id,
        "copy_source_data": False,
        "copy_source_constraints": False,
    }
    with patch.object(models, "duplicate_column") as mock_infer:
        mock_infer.return_value = target_col
        response = client.post(
            f"/api/db/v0/tables/{column_test_table.id}/columns/",
            data=data
        )
    assert response.status_code == 201
    response_col = response.json()
    assert response_col["name"] == target_col.name
    assert response_col["type"] == target_col.db_type.id

    assert mock_infer.call_args[0] == (
        column_test_table.oid,
        column,
        column_test_table.schema._sa_engine,
    )
    assert mock_infer.call_args[1] == {
        "new_column_name": data["name"],
        "copy_data": data["copy_source_data"],
        "copy_constraints": data["copy_source_constraints"]
    }


def test_column_duplicate_when_missing(column_test_table, client):
    data = {
        "source_column": 3000,
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    assert response.status_code == 400
    response_data = response.json()[0]
    assert 2151 == response_data['code']
    assert "object does not exist" in response_data['message']


def test_column_duplicate_some_parameters(column_test_table, client):
    data = {
        "copy_source_constraints": True,
    }
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data=data
    )
    response_data = response.json()
    assert response.status_code == 400
    assert response_data[0]['message'] == "This field is required."
    assert response_data[0]['field'] == "source_column"


def test_column_duplicate_no_parameters(column_test_table, client):
    response = client.post(
        f"/api/db/v0/tables/{column_test_table.id}/columns/", data={}
    )
    response_data = response.json()
    assert response.status_code == 400
    assert response_data[0]["message"] == "This field is required."
    assert response_data[0]["field"] == "type"
