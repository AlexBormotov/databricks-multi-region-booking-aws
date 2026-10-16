from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from ops import session

NOW = datetime(2027, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def aws(monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    with mock_aws():
        yield


def test_reaper_decision(aws):
    ssm = boto3.client("ssm", region_name=session.HOME)
    assert not session.due(ssm, NOW)  # no session
    session.set_expiry(ssm, NOW, hours=2)
    assert not session.due(ssm, NOW + timedelta(hours=1, minutes=59))
    assert session.due(ssm, NOW + timedelta(hours=2))
    session.clear_expiry(ssm)
    session.clear_expiry(ssm)  # idempotent
    assert not session.due(ssm, NOW + timedelta(days=1))


def test_empty_bucket_removes_every_version(aws):
    s3 = boto3.client("s3", region_name=session.HOME)
    s3.create_bucket(Bucket="landing")
    s3.put_bucket_versioning(Bucket="landing", VersioningConfiguration={"Status": "Enabled"})
    for i in range(3):
        s3.put_object(Bucket="landing", Key="events/a.json", Body=str(i).encode())
    s3.delete_object(Bucket="landing", Key="events/a.json")
    assert session.empty_bucket(s3, "landing") == 4  # three versions and a delete marker
    assert "Versions" not in s3.list_object_versions(Bucket="landing")
