from sqlalchemy import text
from db.types import base

TEXT = "text"
BOOLEAN = "boolean"
NUMERIC = "numeric"


def install_all_casts(engine):
    create_boolean_casts(engine)


def create_boolean_casts(engine):
    not_bool_exception_str = f"RAISE EXCEPTION '% is not a {BOOLEAN}', $1;"
    type_body_map = {
        TEXT: f"""
        DECLARE
        istrue {BOOLEAN};
        BEGIN
          SELECT lower($1)='t' OR lower($1)='true' INTO istrue;
          IF istrue OR lower($1)='f' OR lower($1)='false' THEN
            RETURN istrue;
          END IF;
          {not_bool_exception_str}
        END;
        """,
        NUMERIC: f"""
        BEGIN
          IF $1<>0 AND $1<>1 THEN
            {not_bool_exception_str}
          END IF;
          RETURN $1<>0;
        END;
        """
    }
    for type_, body in type_body_map.items():
        query = assemble_function_creation_sql(type_, 'boolean', body)
        with engine.begin() as conn:
            conn.execute(text(query))


def assemble_function_creation_sql(argument_type, target_type, function_body):
    function_name = get_cast_function_name(target_type)
    return f"""
    CREATE OR REPLACE FUNCTION {function_name}({argument_type})
    RETURNS {target_type}
    AS $$
    {function_body}
    $$ LANGUAGE plpgsql;
    """

def get_cast_function_name(target_type):
    unqualified_type_name = target_type.split('.')[-1].lower()
    bare_function_name = f"cast_to_{target_type}"
    return f"{base.get_qualified_name(bare_function_name)}"
