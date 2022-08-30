import pytest

from cardano.wt.mint import Mint

def test_does_not_allow_instantiation():
    try:
        Mint.RebateCalculator()
        assert False, 'Able to instantiate an instance of utils class'
    except ValueError as e:
        assert 'static class' in str(e)

@pytest.mark.parametrize("policies, assets, chars, expected", [
    (1, 0, 1, 0),
    (5, 0, 1, 0),
    (1, 0, 5, 0),
    (1, 1, 0, 1407406),
    (1, 1, 1, 1444443),
    (1, 1, 32, 1555554),
    (1, 110, 3520, 23777754),
    (60, 60, 1920, 21222201)
])
def test_should_return_calculated_values(policies, assets, chars, expected):
    actual = Mint.RebateCalculator.calculate_rebate_for(policies, assets, chars)
    assert actual == expected, f"Failed for combination: {policies}, {assets}, {chars} => {expected}"
