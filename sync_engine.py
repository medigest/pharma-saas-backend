from app.services.sync_service import push_changes, pull_changes

async def full_sync(tenant_id: str, last_sync: str):
    remote = await pull_changes(tenant_id, last_sync)
    local = await push_changes(tenant_id)
    return {
        "pulled": remote,
        "pushed": local,
    }
