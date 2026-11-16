from scripts.mamo_tsp_audit import audit_code


def test_dict_cost_and_range_expression():
    code = '''n = 4
cities = list(range(1, n+1))
cost = {(1,2): 1, (2,1): 1, (1,3): 10, (3,1): 10, (1,4): 10, (4,1): 10,
        (2,3): 1, (3,2): 1, (2,4): 10, (4,2): 10, (3,4): 1, (4,3): 1}
'''
    result = audit_code(code)
    assert result["objective"] == 13


def test_list_matrix_and_node_alias():
    code = '''nodes = ["A", "B", "C"]
cost = [[0, 1, 10], [1, 0, 1], [10, 1, 0]]
'''
    result = audit_code(code)
    assert result["objective"] == 12
    assert result["tour"] == ("A", "B", "C", "A")
