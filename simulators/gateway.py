import uuid

SUCCESS = "SUCCESS"
FAILED = "FAILED"


class GatewayTimeout(Exception):
    pass


def pay(amount: int, mode: str, simulate: str = "success"):
    if simulate == "timeout":
        raise GatewayTimeout()
    if simulate == "failure":
        return FAILED, None
    return SUCCESS, f"{mode[:3]}-{uuid.uuid4().hex[:12].upper()}"
