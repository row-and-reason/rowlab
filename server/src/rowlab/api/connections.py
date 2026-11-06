from fastapi import APIRouter

from rowlab.core import connections
from rowlab.core.connections import Connection, ConnectionInput

router = APIRouter(prefix="/v1/settings/connections", tags=["settings"])


@router.get("", operation_id="listConnections")
def list_connections() -> list[Connection]:
    """Connections to S3-compatible storage, by name. Secret keys are never returned."""
    return connections.list_connections()


@router.post("", operation_id="createConnection", status_code=201)
def create_connection(data: ConnectionInput) -> Connection:
    return connections.create_connection(data)


@router.put("/{connection_id}", operation_id="updateConnection")
def update_connection(connection_id: str, data: ConnectionInput) -> Connection:
    """Change a connection; leave out `secret_access_key` to keep the saved one."""
    return connections.update_connection(connection_id, data)


@router.delete("/{connection_id}", operation_id="deleteConnection", status_code=204)
def delete_connection(connection_id: str) -> None:
    connections.delete_connection(connection_id)
