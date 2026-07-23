from eth_account import Account
from eth_account.messages import encode_typed_data

from py_clob_client_v2.order_utils.exchange_order_builder_v2 import (
    ExchangeOrderBuilderV2,
)
from py_clob_client_v2.order_utils.model.order_data_v2 import OrderDataV2
from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2

from scripts.agentic_polymarket_order_signer import (
    AgenticExchangeOrderBuilderV2,
    OnchainOSOrderSigner,
    poly_1271_signing_message,
)


EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
FUNDER = "0x577108052c8D862984B724668E2f6035Eb6Fa5c5"


def _order_data() -> OrderDataV2:
    return OrderDataV2(
        maker=FUNDER,
        signer=FUNDER,
        tokenId="123456789",
        makerAmount="100000",
        takerAmount="5000000",
        side=0,
        signatureType=SignatureTypeV2.POLY_1271,
        timestamp="1784764800000",
    )


def test_agentic_envelope_matches_official_sdk_byte_for_byte():
    account = Account.create()
    official_signer = type(
        "OfficialSigner",
        (),
        {
            "private_key": account.key,
            "address": lambda self: account.address,
            "get_chain_id": lambda self: 137,
        },
    )()
    official = ExchangeOrderBuilderV2(
        EXCHANGE, 137, official_signer, generate_salt=lambda: 7
    ).build_signed_order(_order_data())

    captured = []

    def external_sign(message: dict) -> str:
        captured.append(message)
        signed = Account.sign_message(
            encode_typed_data(full_message=message), private_key=account.key
        )
        return "0x" + signed.signature.hex()

    agentic_signer = OnchainOSOrderSigner(
        account.address, sign_typed_data=external_sign
    )
    agentic = AgenticExchangeOrderBuilderV2(
        EXCHANGE, 137, agentic_signer, generate_salt=lambda: 7
    ).build_signed_order(_order_data())

    assert agentic.signature == official.signature
    assert captured[0]["primaryType"] == "TypedDataSign"
    assert captured[0]["message"]["verifyingContract"] == FUNDER
    assert captured[0]["message"]["contents"]["signatureType"] == "3"


def test_signer_contains_no_private_key():
    signer = OnchainOSOrderSigner(
        "0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38",
        sign_typed_data=lambda _: "0x" + "11" * 65,
    )
    assert signer.address() == "0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38"
    assert signer.get_chain_id() == 137
    assert not hasattr(signer, "private_key")
