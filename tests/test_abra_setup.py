import pytest

from brownie.convert import to_string
from brownie.network.state import TxHistory
from brownie import chain, Wei



def test_mim_should_be_minted_after_depositing_collateral(
    strategy, vault, yvMIM, token, token_whale, mim, gov
):
    # Make sure there is no balance before the first deposit
    assert yvMIM.balanceOf(strategy) == 0

    amount = 25 * (10 ** token.decimals())
    token.approve(vault.address, amount, {"from": token_whale})
    vault.deposit(amount, {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Minted DAI should be deposited in yvDAI
    assert mim.balanceOf(strategy) == 0
    assert yvMIM.balanceOf(strategy) > 0


def DISABLED_WETH_test_ethToWant_should_convert_to_yvweth(
    strategy, price_oracle_eth, RELATIVE_APPROX
):
    price = price_oracle_eth.latestAnswer()
    assert pytest.approx(
        strategy.ethToWant(Wei("1 ether")), rel=RELATIVE_APPROX
    ) == Wei("1 ether") / (price / 1e18)
    assert pytest.approx(
        strategy.ethToWant(Wei(price * 420)), rel=RELATIVE_APPROX
    ) == Wei("420 ether")
    assert pytest.approx(
        strategy.ethToWant(Wei(price * 0.5)), rel=RELATIVE_APPROX
    ) == Wei("0.5 ether")
