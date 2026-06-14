from backend.app.parsers.sql_parser import analyze_sql


def test_sql_parser_extracts_tables_columns_where_and_params():
    result = analyze_sql(
        """
        SELECT CUSTOMER_NO, STATUS
          FROM TB_CUSTOMER C
          JOIN TB_BRANCH B ON B.BRANCH_ID = C.BRANCH_ID
         WHERE CUSTOMER_NO = #{customerNo}
           AND USE_YN = 'Y'
        """
    )

    assert result["crud"] == ["SELECT"]
    assert "TB_CUSTOMER" in result["tables"]
    assert "TB_BRANCH" in result["tables"]
    assert "CUSTOMER_NO" in result["columns"]
    assert "customerNo" in result["parameters"]
    assert any("USE_YN" in condition for condition in result["where_conditions"])
    assert any("TB_BRANCH" in join for join in result["joins"])
