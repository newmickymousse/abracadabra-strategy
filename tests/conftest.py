import pytest
from brownie import config, convert, interface, Contract


@pytest.fixture(autouse=True)
def isolation(fn_isolation):
    pass

@pytest.fixture
def gov(accounts):
    yield accounts.at("0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52", force=True)


@pytest.fixture
def user(accounts):
    yield accounts[0]


@pytest.fixture
def rewards(accounts):
    yield accounts[1]


@pytest.fixture
def guardian(accounts):
    yield accounts[2]


@pytest.fixture
def management(accounts):
    yield accounts[3]


@pytest.fixture
def strategist(accounts):
    yield accounts.at("0x16388463d60FFE0661Cf7F1f31a7D658aC790ff7", force=True)


@pytest.fixture
def keeper(accounts):
    yield accounts[5]


@pytest.fixture
def token():
    token_address = "0xa258C4606Ca8206D8aA700cE2143D7db854D168c"  # yvWETH
    yield Contract(token_address)


@pytest.fixture
def token_whale(accounts):
    yield accounts.at(
        "0xf5bce5077908a1b7370b9ae04adc565ebd643966", force=True
    )  # BentoBox yvWETH


@pytest.fixture
def weth_whale(accounts):
    yield accounts.at("0xC1AAE9d18bBe386B102435a8632C8063d31e747C", force=True)


@pytest.fixture
def dai():
    dai_address = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
    yield Contract(dai_address)

@pytest.fixture
def mim():
    mim_address = "0x99D8a9C45b2ecA8864373A26D1459e3Dff1e17F3"
    yield Contract(mim_address)

@pytest.fixture
def mim_whale(accounts):
    yield accounts.at("0x5a6a4d54456819380173272a5e8e9b9904bdf41b", force=True)


@pytest.fixture
def borrow_token(mim):
    yield mim


@pytest.fixture
def borrow_whale(mim_whale):
    yield mim_whale

@pytest.fixture
def yvMIM(new_mim_yvault):
    yield new_mim_yvault

@pytest.fixture
def yvault(new_mim_yvault):
    yield new_mim_yvault

@pytest.fixture
def price_oracle_eth():
    # WILL NOT BE USED FOR ETH
    chainlink_oracle = interface.AggregatorInterface(
        "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"
    )
    yield chainlink_oracle


@pytest.fixture
def yvWETH():
    vault_address = "0xa258C4606Ca8206D8aA700cE2143D7db854D168c"
    yield Contract(vault_address)


@pytest.fixture
def router():
    sushiswap_router = interface.ISwap("0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F")
    yield sushiswap_router


@pytest.fixture
def amount(accounts, token, user):
    amount = 10 * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate an exchange address to use it's funds.
    reserve = accounts.at("0xf5bce5077908a1b7370b9ae04adc565ebd643966", force=True)
    token.transfer(user, amount, {"from": reserve})
    yield amount


@pytest.fixture
def weth():
    token_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    yield Contract(token_address)


@pytest.fixture
def weth_amount(user, weth):
    weth_amount = 10 ** weth.decimals()
    user.transfer(weth, weth_amount)
    yield weth_amount


@pytest.fixture
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    yield vault


@pytest.fixture
def new_yvweth_yvault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    yield vault

@pytest.fixture
def new_mim_yvault(pm, gov, rewards, guardian, management, mim):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(mim, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    yield vault



@pytest.fixture
def osmProxy():
    # Allow the strategy to query the OSM proxy
    osm = Contract("0xCF63089A8aD2a9D8BD6Bb8022f3190EB7e1eD0f1")
    yield osm


@pytest.fixture
def abracadabra():
    yield Contract("0x920D9BD936Da4eAFb5E25c6bDC9f6CB528953F9f")


@pytest.fixture
def healthCheck():
    yield Contract("0xDDCea799fF1699e98EDF118e0629A974Df7DF012")


@pytest.fixture
def test_strategy(
    TestStrategy,
    strategist,
    vault,
    new_mim_yvault,
    token,
    abracadabra,
    price_oracle_eth,
    gov,
):
    strategy = strategist.deploy(
        TestStrategy,
        vault,
        new_mim_yvault,
        "yvWETH-MIM-test",
        abracadabra,
        price_oracle_eth
    )
    # strategy.setLeaveDebtBehind(False, {"from": gov})
    strategy.setDoHealthCheck(True, {"from": gov})

    # set a high acceptable max base fee to avoid changing test behavior
    # strategy.setMaxAcceptableBaseFee(1500 * 1e9, {"from": gov})

    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 1_000, {"from": gov})

    yield strategy


@pytest.fixture
def strategy(strategist, vault, Strategy, gov, new_mim_yvault, abracadabra, price_oracle_eth):
    strategy = strategist.deploy(
        Strategy,
        vault,
        new_mim_yvault,
        "yvWETH-MIM",
        abracadabra,
        price_oracle_eth)


    # strategy = Strategy.at(cloner.original())
    # strategy.setLeaveDebtBehind(False, {"from": gov})
    strategy.setDoHealthCheck(True, {"from": gov})

    # set a high acceptable max base fee to avoid changing test behavior
    # strategy.setMaxAcceptableBaseFee(1500 * 1e9, {"from": gov})

    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 1_000, {"from": gov})

    yield strategy

@pytest.fixture(scope="session")
def RELATIVE_APPROX():
    yield 1e18 #1 whole unit in tokens with 18 decimals
