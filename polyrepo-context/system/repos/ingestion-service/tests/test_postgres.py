from ingestion.connectors.postgres import discover_columns


class FakeConn:
    def execute(self, sql, params):
        class R:
            def fetchall(self_inner):
                return [("email", "text", "YES", "tags: pii,email")]
        return R()


def test_discover_columns_maps_name_type_nullable():
    assert discover_columns(FakeConn(), "crm", "customers") == [
        {"name": "email", "type": "text", "nullable": True}]
