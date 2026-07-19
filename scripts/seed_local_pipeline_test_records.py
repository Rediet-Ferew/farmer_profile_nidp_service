"""Seed local farmers for end-to-end Fayda dedup and approval testing.

Run with:

    ./odoo-bin shell -c debian/odoo.conf -d odoo_dev --no-http \
        < custom_addons/openg2p-farmer-profile-dedup/scripts/seed_local_pipeline_test_records.py

The mock API recognizes UID values 100000000001 through 100000000030 and
returns deterministic successful Fayda data for them.
"""

import base64
from datetime import date


SUCCESS_MESSAGE = "Registration has processed successfully."
TEST_COUNT = 30
TEST_PREFIX = "LOCAL-FAYDA-PIPELINE"
UID_START = 100000000001


def format_uid(value):
    clean_value = str(value)
    return f"{clean_value[:4]} {clean_value[4:8]} {clean_value[8:12]}"


def model(name):
    if name not in env:
        raise Exception(f"Missing model {name}. Is the needed module installed in this database?")
    return env[name].sudo()


Partner = model("res.partner")
RegId = model("g2p.reg.id")
IdType = model("g2p.id.type")
ImportSource = model("g2p.import.source")
PhoneNumber = model("g2p.phone.number")
LandInfo = model("g2p.land.information")
Kebele = model("g2p.kebele")
Enumerator = model("g2p.enumerator")
Membership = model("g2p.group.membership")
MembershipKind = model("g2p.group.membership.kind")
GroupKind = model("g2p.group.kind")
Income = model("g2p.hh.income")
Language = model("g2p.lang")
Gender = model("gender.type")
StorageFile = model("storage.file")
StorageBackend = model("storage.backend")


def get_or_create(model_obj, domain, vals):
    record = model_obj.search(domain, limit=1)
    if record:
        return record
    return model_obj.create(vals)


def get_id_type(name):
    return get_or_create(IdType, [("name", "=", name)], {"name": name})


def get_gender_value(label):
    gender = Gender.search(["|", ("value", "=", label), ("code", "=", label)], limit=1)
    if not gender:
        gender = Gender.search(
            ["|", ("value", "=ilike", label), ("code", "=ilike", label)],
            limit=1,
        )
    if not gender:
        gender = Gender.create({"code": label, "value": label})
    return gender.value


def get_required_reference_data():
    source = get_or_create(ImportSource, [("name", "ilike", "Pula")], {"name": "Pula"})
    language = Language.search([("name", "ilike", "English")], limit=1) or Language.search([], limit=1)
    if not language:
        language = Language.create({"name": "English"})

    male_gender_value = get_gender_value("Male")
    female_gender_value = get_gender_value("Female")

    income = get_or_create(
        Income,
        ["|", ("code", "=", "LOCAL_PIPELINE_SEED"), ("name", "=", "Local Pipeline Seed Income")],
        {"name": "Local Pipeline Seed Income", "code": "LOCAL_PIPELINE_SEED"},
    )
    enumerator = get_or_create(
        Enumerator,
        [("enumerator_user_id", "=", "LOCAL_PIPELINE_ENUM")],
        {
            "name": "Local Pipeline Enumerator",
            "enumerator_user_id": "LOCAL_PIPELINE_ENUM",
            "data_collection_date": date.today(),
        },
    )
    head_kind = get_or_create(
        MembershipKind,
        [("name", "=", "Head")],
        {"name": "Head", "is_unique": True},
    )
    household_kind = get_or_create(GroupKind, [("name", "=", "Household")], {"name": "Household"})

    kebele = Kebele.search(
        [
            ("code", "!=", False),
            ("woreda", "!=", False),
            ("woreda.code", "!=", False),
            ("woreda.zone", "!=", False),
            ("woreda.zone.code", "!=", False),
            ("woreda.zone.region", "!=", False),
            ("woreda.zone.region.code", "!=", False),
        ],
        limit=1,
    )
    if not kebele:
        raise Exception("No complete region/zone/woreda/kebele hierarchy found in this database.")

    backend = None
    try:
        backend = env.ref("storage_backend.default_storage_backend").sudo()
    except Exception:
        backend = StorageBackend.search([], limit=1)
    if not backend:
        raise Exception("No storage backend found. A backend is needed to attach test land certificates.")

    return {
        "source": source,
        "language": language,
        "income": income,
        "enumerator": enumerator,
        "head_kind": head_kind,
        "household_kind": household_kind,
        "kebele": kebele,
        "woreda": kebele.woreda,
        "zone": kebele.woreda.zone,
        "region": kebele.woreda.zone.region,
        "backend": backend,
        "male_gender_value": male_gender_value,
        "female_gender_value": female_gender_value,
    }


def create_certificate(index, backend):
    name = f"{TEST_PREFIX}-land-certificate-{index:03d}.txt"
    existing = StorageFile.search([("name", "=", name)], limit=1)
    if existing:
        return existing

    data = base64.b64encode(f"Local Fayda pipeline certificate {index:03d}".encode()).decode()
    return StorageFile.create(
        {
            "name": name,
            "backend_id": backend.id,
            "data": data,
        }
    )


def delete_existing_child_rows(partner):
    partner.reg_ids.filtered(lambda row: row.id_type.name in ["UID", "FIN", "FAN", "RID", "Mavuno Farmer ID"]).unlink()
    partner.phone_number_ids.unlink()
    partner.land_information_ids.filtered(lambda row: row.land_id and row.land_id.startswith(TEST_PREFIX)).unlink()
    Membership.search([("individual", "=", partner.id)]).unlink()


def upsert_test_partner(index, refs):
    uid_value = format_uid(UID_START + index - 1)
    mavuno_value = f"{TEST_PREFIX}-MAVUNO-{index:03d}"
    unique_id = f"{TEST_PREFIX}-{index:03d}"

    existing_reg_id = RegId.search(
        [
            ("id_type.name", "=", "Mavuno Farmer ID"),
            ("value", "=", mavuno_value),
        ],
        limit=1,
    )
    partner = existing_reg_id.partner_id if existing_reg_id else Partner.browse()
    if not partner and "unique_id" in Partner._fields:
        partner = Partner.search([("unique_id", "=", unique_id)], limit=1)

    vals = {
        "name": f"Seed Farmer {index:03d}",
        "given_name": "Seed",
        "family_name": "Farmer",
        "addl_name": "Pipeline",
        "gf_name_eng": "Pipeline",
        "first_name_amh": "ሙከራ",
        "family_name_amh": "ገበሬ",
        "gf_name_amh": "መስመር",
        "is_registrant": True,
        "is_group": False,
        "active": True,
        "is_farmer": "yes",
        "state": "draft",
        "gender": refs["male_gender_value"] if index % 2 else refs["female_gender_value"],
        "birthdate": "1990-01-01",
        "birthdate_ec": "1982-04-23",
        "registration_date": date.today(),
        "primary_Language": refs["language"].id,
        "rec_import_source": refs["source"].id,
        "region": refs["region"].id,
        "zone": refs["zone"].id,
        "woreda": refs["woreda"].id,
        "kebele": refs["kebele"].id,
        "hh_is_household_head": "yes",
        "number_of_males_in_family": 2,
        "number_of_females_in_family": 2,
        "number_of_children_in_family": 2,
        "size_of_family": 4,
        "farming_type": "crop_farming",
        "martial_status": "married",
        "education": "basic",
        "is_psnp_user": False,
        "hh_income_type": [(6, 0, [refs["income"].id])],
        "enumerator_id": refs["enumerator"].id,
        "unique_id": unique_id,
    }

    vals = {key: value for key, value in vals.items() if key in Partner._fields}

    if partner:
        partner.write(vals)
    else:
        partner = Partner.create(vals)

    delete_existing_child_rows(partner)

    household = get_or_create(
        Partner,
        [("name", "=", f"{TEST_PREFIX}-HOUSEHOLD-{index:03d}"), ("is_group", "=", True)],
        {
            "name": f"{TEST_PREFIX}-HOUSEHOLD-{index:03d}",
            "is_registrant": True,
            "is_group": True,
            "active": True,
            "kind": refs["household_kind"].id,
            "region": refs["region"].id,
            "zone": refs["zone"].id,
            "woreda": refs["woreda"].id,
            "kebele": refs["kebele"].id,
            "enumerator_id": refs["enumerator"].id,
        },
    )
    Membership.create(
        {
            "group": household.id,
            "individual": partner.id,
            "kind": [(6, 0, [refs["head_kind"].id])],
        }
    )

    phone_vals = {"partner_id": partner.id, "phone_no": f"+251911{index:06d}"}
    if "phone_type" in PhoneNumber._fields:
        phone_vals["phone_type"] = "primary"
    PhoneNumber.create(phone_vals)

    cert = create_certificate(index, refs["backend"])
    LandInfo.create(
        {
            "partner_id": partner.id,
            "total_land_area": 1.25 + (index / 100),
            "land_certificate": cert.id,
            "land_id": f"{TEST_PREFIX}-LAND-{index:03d}",
            "ownership_type": "owner",
            "land_kebele": refs["kebele"].id,
        }
    )

    id_types = {
        "UID": get_id_type("UID"),
        "FAN": get_id_type("FAN"),
        "RID": get_id_type("RID"),
        "Mavuno Farmer ID": get_id_type("Mavuno Farmer ID"),
    }

    base_id_vals = {
        "partner_id": partner.id,
        "status": False,
        "description": False,
        "expiry_date": False,
    }
    if "fayda_processed" in RegId._fields:
        base_id_vals["fayda_processed"] = False
    if "fayda_response_status" in RegId._fields:
        base_id_vals["fayda_response_status"] = False

    RegId.create({**base_id_vals, "id_type": id_types["UID"].id, "value": uid_value})
    RegId.create(
        {
            **base_id_vals,
            "id_type": id_types["Mavuno Farmer ID"].id,
            "value": mavuno_value,
            "status": "valid",
            "description": SUCCESS_MESSAGE,
        }
    )

    return partner, uid_value, mavuno_value


refs = get_required_reference_data()
created_or_updated = []
for i in range(1, TEST_COUNT + 1):
    created_or_updated.append(upsert_test_partner(i, refs))

seeded_partner_ids = [item[0].id for item in created_or_updated]
env.cr.execute(
    """
    UPDATE res_partner
       SET farmer_id = NULL
     WHERE id = ANY(%s)
       AND state = 'draft'
    """,
    (seeded_partner_ids,),
)
env.cr.commit()

print(f"seeded_or_refreshed={len(created_or_updated)}")
print("uid_values=" + ",".join(item[1] for item in created_or_updated))
print("mavuno_values=" + ",".join(item[2] for item in created_or_updated))
print("next_steps=run mock API, then run farmer dedup service against odoo_dev")
