"""Clear stored farmer IDs for local pipeline seed records.

Run with:

    TEST_START_INDEX=31 TEST_COUNT=30 ./odoo-bin shell -c debian/odoo.conf -d odoo_dev --no-http \
        < custom_addons/openg2p-farmer-profile-dedup/scripts/clear_seed_farmer_ids.py

This intentionally uses SQL instead of ORM write because farmer_id is a stored
computed field on res.partner. The approval service can then recreate it later.
"""

import os


TEST_PREFIX = os.getenv("TEST_PREFIX", "LOCAL-FAYDA-PIPELINE")
TEST_START_INDEX = int(os.getenv("TEST_START_INDEX", "1"))
TEST_COUNT = int(os.getenv("TEST_COUNT", "30"))

unique_ids = [
    f"{TEST_PREFIX}-{index:03d}"
    for index in range(TEST_START_INDEX, TEST_START_INDEX + TEST_COUNT)
]

env.cr.execute(
    """
    SELECT id, unique_id, farmer_id
    FROM res_partner
    WHERE unique_id = ANY(%s)
      AND is_farmer = 'yes'
    ORDER BY unique_id
    """,
    (unique_ids,),
)
before_rows = env.cr.fetchall()

env.cr.execute(
    """
    UPDATE res_partner
       SET farmer_id = NULL,
           write_date = NOW()
     WHERE unique_id = ANY(%s)
       AND is_farmer = 'yes'
    RETURNING id, unique_id
    """,
    (unique_ids,),
)
updated_rows = env.cr.fetchall()
env.cr.commit()

print(f"target_index_range={TEST_START_INDEX}-{TEST_START_INDEX + TEST_COUNT - 1}")
print(f"matched_before={len(before_rows)}")
print(f"cleared_farmer_ids={len(updated_rows)}")
print("cleared_unique_ids=" + ",".join(row[1] for row in updated_rows))
