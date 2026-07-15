# OpenG2P Farmer Profile Dedup Service

Standalone FastAPI service for farmer-profile national ID deduplication.

The service will:

- fetch pending `UID`, `FAN`, and `RID` values directly from the farmer profile database
- send only IDs that have not been deduplicated before
- call the NIDP/Fayda get-data-by-id API
- update `g2p_reg_id` and selected `res_partner` fields directly in the farmer profile database
- store `fayda_processed` and `fayda_response_status` on ID rows for traceability

This package is intentionally separate from the Odoo registry REST API flow.

