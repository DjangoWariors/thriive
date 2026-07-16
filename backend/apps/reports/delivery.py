"""Outbound artifact delivery — pushes a rendered extract to a DeliveryTarget.

The secret is read from the environment variable the target names (never the DB).
Failures raise DeliveryError; the caller records it on the execution.
"""
import os
from io import BytesIO

from apps.core.exceptions import BusinessError

from .models import DeliveryTarget


class DeliveryError(BusinessError):
    pass


def _secret(target: DeliveryTarget) -> str:
    if not target.credential_env:
        return ''
    value = os.environ.get(target.credential_env, '')
    if not value:
        raise DeliveryError(
            f'Environment variable "{target.credential_env}" for delivery target '
            f'"{target.code}" is not set on this server.'
        )
    return value


def push_to_target(target: DeliveryTarget, filename: str, content: bytes) -> str:
    """Push one artifact; returns the remote path/key written."""
    if target.kind == DeliveryTarget.S3:
        return _push_s3(target, filename, content)
    if target.kind == DeliveryTarget.SFTP:
        return _push_sftp(target, filename, content)
    raise DeliveryError(f'Unknown delivery target kind "{target.kind}".')


def _push_s3(target: DeliveryTarget, filename: str, content: bytes) -> str:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise DeliveryError('boto3 is not installed on this server.') from exc

    cfg = target.config or {}
    bucket = cfg.get('bucket')
    if not bucket:
        raise DeliveryError(f'Delivery target "{target.code}" has no S3 bucket configured.')
    key = f"{cfg.get('prefix', '').strip('/')}/{filename}".lstrip('/')

    kwargs = {}
    if cfg.get('region'):
        kwargs['region_name'] = cfg['region']
    if cfg.get('access_key_id'):
        kwargs['aws_access_key_id'] = cfg['access_key_id']
        kwargs['aws_secret_access_key'] = _secret(target)
    client = boto3.client('s3', **kwargs)
    client.put_object(Bucket=bucket, Key=key, Body=content)
    return f's3://{bucket}/{key}'


def _push_sftp(target: DeliveryTarget, filename: str, content: bytes) -> str:
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover
        raise DeliveryError('paramiko is not installed on this server.') from exc

    cfg = target.config or {}
    host = cfg.get('host')
    if not host:
        raise DeliveryError(f'Delivery target "{target.code}" has no SFTP host configured.')
    remote_path = f"{(cfg.get('path') or '.').rstrip('/')}/{filename}"
    secret = _secret(target)  # resolve before dialing — fail fast on missing config

    transport = paramiko.Transport((host, int(cfg.get('port', 22))))
    try:
        transport.connect(username=cfg.get('username', ''), password=secret)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.putfo(BytesIO(content), remote_path)
        sftp.close()
    finally:
        transport.close()
    return remote_path


def probe(target: DeliveryTarget) -> dict:
    """Connectivity check for the admin UI's Test button — writes a tiny marker file."""
    path = push_to_target(target, '.thriive-connectivity-check', b'ok')
    return {'ok': True, 'written': path}
