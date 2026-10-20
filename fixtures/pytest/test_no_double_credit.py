"""Example: prove your handler credits exactly once under duplicates."""
from paymock.retry import deliver_duplicate
from paymock.store import Transaction
from paymock.webhooks import build


def test_duplicate_webhooks_do_not_double_credit(paymock_receiver):
    txn = Transaction(reference="T-DOUBLE-1", amount=50000, currency="NGN",
                      email="me@x.dev", gateway="paystack")
    report = deliver_duplicate(paymock_receiver.url, "paystack", txn, "success", copies=3)

    assert report.delivered and report.duplicates == 2
    assert len(paymock_receiver.received) == 3          # 3 deliveries...
    assert sum(paymock_receiver.credits.values()) == 1  # ...but exactly 1 credit
