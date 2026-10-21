"""Room-night claims on DynamoDB from the spike that ADR 0001 rejected and ADR 0002 adopted; the
store itself is `booking.service`. Kept for the MRSC race script.

A claim is one conditional `PutItem` per night. MRSC tables have no transactions, so a multi-night
claim that loses a night part-way deletes the nights it already took (a compensating step).
"""

from datetime import date

from botocore.exceptions import ClientError


def key(room_id: str, night: date) -> dict:
    return {"room_night": {"S": f"{room_id}#{night.isoformat()}"}}


def claim(client, table: str, booking_id: str, room_id: str, nights: list[date]) -> bool:
    """True if every night is now held by `booking_id`; False, with nothing held, otherwise."""
    taken = []
    for night in nights:
        try:
            client.put_item(
                TableName=table,
                Item={**key(room_id, night), "booking_id": {"S": booking_id}},
                ConditionExpression="attribute_not_exists(room_night)",
            )
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            release(client, table, booking_id, room_id, taken)
            return False
        taken.append(night)
    return True


def release(client, table: str, booking_id: str, room_id: str, nights: list[date]) -> None:
    """Deletes only the nights this booking holds, so a release never frees another's night."""
    for night in nights:
        try:
            client.delete_item(
                TableName=table,
                Key=key(room_id, night),
                ConditionExpression="booking_id = :b",
                ExpressionAttributeValues={":b": {"S": booking_id}},
            )
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
