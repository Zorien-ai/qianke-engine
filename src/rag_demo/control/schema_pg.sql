CREATE EXTENSION IF NOT EXISTS vector;

-- 控制面 PostgreSQL schema（由 SQLite schema 生成，P1 兼容阶段）
-- __SCHEMA__ 由 repository 替换为实际 schema
CREATE SCHEMA IF NOT EXISTS __SCHEMA__;

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_product (
  "product_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "category" TEXT NOT NULL,
  "price" NUMERIC(12,2) NOT NULL,
  "stock" INTEGER NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_order (
  "order_id" TEXT PRIMARY KEY,
  "buyer_id" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "total_amount" NUMERIC(12,2) NOT NULL,
  "confirmation_hash" TEXT,
  "snapshot_json" TEXT NOT NULL,
  "idempotency_key" TEXT,
  "source_order_id" TEXT,
  "created_at" TEXT NOT NULL,
  "confirmed_at" TEXT,
  "original_amount" NUMERIC(12,2) NOT NULL DEFAULT 0,
  "discount_amount" NUMERIC(12,2) NOT NULL DEFAULT 0,
  "quote_id" TEXT,
  "merchant_id" TEXT,
  "policy_ids_json" TEXT NOT NULL DEFAULT '[]',
  UNIQUE ("idempotency_key")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_order_item (
  "order_id" TEXT NOT NULL,
  "product_id" TEXT NOT NULL,
  "quantity" INTEGER NOT NULL,
  "unit_price" NUMERIC(12,2) NOT NULL,
  PRIMARY KEY ("order_id", "product_id"),
  FOREIGN KEY ("product_id") REFERENCES __SCHEMA__."c_product" ("product_id"),
  FOREIGN KEY ("order_id") REFERENCES __SCHEMA__."c_order" ("order_id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_after_sale (
  "ticket_id" TEXT PRIMARY KEY,
  "order_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "type" TEXT NOT NULL,
  "reason" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'OPEN',
  "refund_amount" NUMERIC(12,2),
  "created_at" TEXT NOT NULL,
  "resolved_at" TEXT,
  "return_tracking_no" TEXT,
  "return_carrier" TEXT,
  "return_shipped_at" TEXT,
  "received_at" TEXT,
  "restocked_at" TEXT,
  FOREIGN KEY ("order_id") REFERENCES __SCHEMA__."c_order" ("order_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_compensation (
  "compensation_id" TEXT PRIMARY KEY,
  "order_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "merchant_id" TEXT NOT NULL,
  "work_item_id" TEXT NOT NULL DEFAULT '',
  "amount" NUMERIC(12,2) NOT NULL,
  "reason" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  UNIQUE ("order_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_quote (
  "quote_id" TEXT PRIMARY KEY,
  "buyer_id" TEXT NOT NULL,
  "friend_id" TEXT NOT NULL,
  "merchant_id" TEXT NOT NULL DEFAULT 'm_gear_002',
  "product_refs_json" TEXT NOT NULL,
  "policy_refs_json" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "created_at" TEXT NOT NULL
);

ALTER TABLE __SCHEMA__.c_order ADD COLUMN IF NOT EXISTS "merchant_id" TEXT;
ALTER TABLE __SCHEMA__.c_quote ADD COLUMN IF NOT EXISTS "merchant_id" TEXT NOT NULL DEFAULT 'm_gear_002';

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_message (
  "message_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "friend_id" TEXT NOT NULL,
  "sender_id" TEXT NOT NULL,
  "receiver_id" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "metadata_json" TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_app_message (
  "message_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "thread_id" TEXT NOT NULL,
  "role" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "metadata_json" TEXT NOT NULL DEFAULT '{}',
  "created_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_friend (
  "owner_id" TEXT NOT NULL,
  "friend_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "note" TEXT NOT NULL DEFAULT '',
  "created_at" TEXT NOT NULL,
  PRIMARY KEY ("owner_id", "friend_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_friend_removed (
  "owner_id" TEXT NOT NULL,
  "friend_id" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  PRIMARY KEY ("owner_id", "friend_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_group (
  "group_id" TEXT NOT NULL,
  "owner_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  PRIMARY KEY ("owner_id", "group_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_group_member (
  "owner_id" TEXT NOT NULL,
  "group_id" TEXT NOT NULL,
  "member_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "sort" INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY ("owner_id", "group_id", "member_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_group_message (
  "message_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "group_id" TEXT NOT NULL,
  "sender_id" TEXT NOT NULL,
  "sender_name" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "metadata_json" TEXT NOT NULL DEFAULT '{}',
  "created_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_mention (
  "mention_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "thread_id" TEXT NOT NULL,
  "message_id" TEXT NOT NULL,
  "token" TEXT NOT NULL,
  "target_id" TEXT NOT NULL,
  "target_name" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "read_at" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_thread_read (
  "owner_id" TEXT NOT NULL,
  "thread_id" TEXT NOT NULL,
  "last_read_at" TEXT NOT NULL,
  PRIMARY KEY ("owner_id", "thread_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_friend_request (
  "request_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "requester_id" TEXT NOT NULL,
  "requester_name" TEXT NOT NULL,
  "requester_kind" TEXT NOT NULL DEFAULT 'user',
  "message" TEXT NOT NULL DEFAULT '',
  "note" TEXT NOT NULL DEFAULT '',
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "created_at" TEXT NOT NULL,
  "resolved_at" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_group_notice (
  "notice_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "group_id" TEXT NOT NULL DEFAULT '',
  "kind" TEXT NOT NULL DEFAULT 'group',
  "title" TEXT NOT NULL,
  "content" TEXT NOT NULL DEFAULT '',
  "status" TEXT NOT NULL DEFAULT 'UNREAD',
  "created_at" TEXT NOT NULL,
  "read_at" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_conversation_pref (
  "owner_id" TEXT NOT NULL,
  "thread_id" TEXT NOT NULL,
  "pinned" INTEGER NOT NULL DEFAULT 0,
  "muted" INTEGER NOT NULL DEFAULT 0,
  "hidden" INTEGER NOT NULL DEFAULT 0,
  "updated_at" TEXT NOT NULL,
  PRIMARY KEY ("owner_id", "thread_id")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion (
  "owner_id" TEXT PRIMARY KEY,
  "name" TEXT NOT NULL,
  "species" TEXT NOT NULL DEFAULT 'digital_companion',
  "persona" TEXT NOT NULL DEFAULT 'warm',
  "appearance" TEXT NOT NULL DEFAULT '',
  "level" INTEGER NOT NULL DEFAULT 1,
  "exp" INTEGER NOT NULL DEFAULT 0,
  "satiety" INTEGER NOT NULL DEFAULT 60,
  "updated_at" TEXT NOT NULL,
  "user_nickname" TEXT NOT NULL DEFAULT '',
  "avatar_path" TEXT NOT NULL DEFAULT '',
  "user_avatar_path" TEXT NOT NULL DEFAULT '',
  "diary_enabled" INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE __SCHEMA__.c_companion
    ADD COLUMN IF NOT EXISTS "diary_enabled" INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion_memory (
  "memory_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "source" TEXT NOT NULL DEFAULT 'explicit',
  "importance" INTEGER NOT NULL DEFAULT 3,
  "reinforced_count" INTEGER NOT NULL DEFAULT 1,
  "last_reinforced_at" TEXT,
  "last_decayed_at" TEXT,
  "status" TEXT NOT NULL DEFAULT 'ACTIVE',
  "pinned" INTEGER NOT NULL DEFAULT 0,
  "compressed_into" TEXT,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  UNIQUE ("owner_id", "kind", "content")
);

ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "importance" INTEGER NOT NULL DEFAULT 3;
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "reinforced_count" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "last_reinforced_at" TEXT;
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "last_decayed_at" TEXT;
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "status" TEXT NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "pinned" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE __SCHEMA__.c_companion_memory
    ADD COLUMN IF NOT EXISTS "compressed_into" TEXT;

CREATE INDEX IF NOT EXISTS idx_c_companion_memory_owner
    ON __SCHEMA__.c_companion_memory ("owner_id", "status", "created_at" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion_memory_digest (
  "digest_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "period" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "source_memory_ids" TEXT NOT NULL DEFAULT '[]',
  "importance" INTEGER NOT NULL DEFAULT 3,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  UNIQUE ("owner_id", "period", "kind")
);

CREATE INDEX IF NOT EXISTS idx_c_companion_memory_digest_owner
    ON __SCHEMA__.c_companion_memory_digest ("owner_id", "period" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion_diary (
  "diary_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "diary_date" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "source_message_count" INTEGER NOT NULL DEFAULT 0,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  UNIQUE ("owner_id", "diary_date")
);

CREATE INDEX IF NOT EXISTS idx_c_companion_diary_owner
    ON __SCHEMA__.c_companion_diary ("owner_id", "diary_date" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.b_chat_user_profile (
  "profile_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1,
  "profile_json" TEXT NOT NULL,
  "profile_text" TEXT NOT NULL,
  "confidence" REAL NOT NULL DEFAULT 0,
  "source_message_count" INTEGER NOT NULL DEFAULT 0,
  "source_session_ids" TEXT NOT NULL DEFAULT '[]',
  "last_message_at" TEXT,
  "extracted_at" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'ACTIVE',
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  UNIQUE ("merchant_id", "buyer_id")
);

CREATE INDEX IF NOT EXISTS idx_b_chat_user_profile_scope
    ON __SCHEMA__.b_chat_user_profile ("merchant_id", "status", "extracted_at" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.b_chat_user_profile_vector (
  "profile_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "embedding" vector(1024),
  "updated_at" TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b_chat_user_profile_vector_scope
    ON __SCHEMA__.b_chat_user_profile_vector ("merchant_id");

CREATE TABLE IF NOT EXISTS __SCHEMA__.b_qianke_user_profile (
  "profile_key" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "profile_json" TEXT NOT NULL DEFAULT '{}',
  "profile_text" TEXT NOT NULL DEFAULT '',
  "order_count" INTEGER NOT NULL DEFAULT 0,
  "order_amount" REAL NOT NULL DEFAULT 0,
  "avg_order_amount" REAL NOT NULL DEFAULT 0,
  "last_order_at" TEXT,
  "top_category" TEXT,
  "has_order" INTEGER NOT NULL DEFAULT 0,
  "has_chat" INTEGER NOT NULL DEFAULT 0,
  "chat_profile_json" TEXT NOT NULL DEFAULT '{}',
  "confidence" REAL NOT NULL DEFAULT 0,
  "source_message_count" INTEGER NOT NULL DEFAULT 0,
  "chat_extracted_at" TEXT,
  "updated_at" TEXT NOT NULL,
  UNIQUE ("merchant_id", "buyer_id")
);

CREATE INDEX IF NOT EXISTS idx_b_qianke_user_profile_scope
    ON __SCHEMA__.b_qianke_user_profile ("merchant_id", "updated_at" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.b_qianke_user_profile_vector (
  "profile_key" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "buyer_id" TEXT NOT NULL,
  "embedding" vector(1024),
  "updated_at" TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b_qianke_user_profile_vector_scope
    ON __SCHEMA__.b_qianke_user_profile_vector ("merchant_id");

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion_rhythm (
  "owner_id" TEXT PRIMARY KEY,
  "enabled" INTEGER NOT NULL DEFAULT 0,
  "timezone" TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  "quiet_start" TEXT NOT NULL DEFAULT '22:00',
  "quiet_end" TEXT NOT NULL DEFAULT '09:00',
  "last_active_at" TEXT,
  "last_checkin_at" TEXT,
  "pause_until" TEXT,
  "unanswered_count" INTEGER NOT NULL DEFAULT 0,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_companion_checkin (
  "checkin_id" TEXT PRIMARY KEY,
  "owner_id" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "ref_id" TEXT NOT NULL DEFAULT '',
  "content" TEXT NOT NULL DEFAULT '',
  "due_at" TEXT NOT NULL,
  "delivered_at" TEXT,
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_companion_checkin_owner
    ON __SCHEMA__.c_companion_checkin ("owner_id", "status", "due_at");

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_logistics_event (
  "event_id" TEXT PRIMARY KEY,
  "provider" TEXT NOT NULL DEFAULT '',
  "order_id" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "occurred_at" TEXT,
  "payload_hash" TEXT NOT NULL DEFAULT '',
  "created_at" TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_logistics_event_order
    ON __SCHEMA__.c_logistics_event ("order_id", "created_at" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_inventory_alert (
  "alert_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "product_id" TEXT NOT NULL,
  "sku" TEXT NOT NULL,
  "sku_spec" TEXT NOT NULL DEFAULT '',
  "available_qty" INTEGER NOT NULL,
  "safety_stock" INTEGER NOT NULL,
  "reorder_qty" INTEGER NOT NULL,
  "severity" TEXT NOT NULL DEFAULT 'WARNING',
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "channel" TEXT NOT NULL DEFAULT 'IN_APP',
  "message" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "last_seen_at" TEXT NOT NULL,
  "acknowledged_at" TEXT,
  "acknowledged_by" INTEGER,
  "resolved_at" TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_c_inventory_alert_sku
    ON __SCHEMA__.c_inventory_alert ("merchant_id", "sku");

CREATE INDEX IF NOT EXISTS idx_c_inventory_alert_queue
    ON __SCHEMA__.c_inventory_alert ("merchant_id", "status", "last_seen_at" DESC);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_client_request (
  "client_id" TEXT NOT NULL,
  "owner_id" TEXT NOT NULL,
  "endpoint" TEXT NOT NULL,
  "fingerprint" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "response_json" TEXT,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  PRIMARY KEY ("client_id", "owner_id", "endpoint")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_reconciliation_run (
  "run_id" TEXT PRIMARY KEY,
  "trigger" TEXT NOT NULL,
  "started_at" TEXT NOT NULL,
  "finished_at" TEXT NOT NULL,
  "ok" INTEGER NOT NULL,
  "checked" INTEGER NOT NULL,
  "legacy" INTEGER NOT NULL,
  "issue_count" INTEGER NOT NULL,
  "issues_json" TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_reconciliation_alert (
  "alert_id" TEXT PRIMARY KEY,
  "run_id" TEXT NOT NULL,
  "order_id" TEXT NOT NULL,
  "issue" TEXT NOT NULL,
  "severity" TEXT NOT NULL DEFAULT 'WARNING',
  "message" TEXT NOT NULL,
  "suggestion" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "last_seen_at" TEXT NOT NULL,
  "read_at" TEXT,
  "resolved_at" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_sop (
  "merchant_id" TEXT NOT NULL,
  "topic" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  PRIMARY KEY ("merchant_id", "topic")
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_tenant (
  "merchant_id" TEXT PRIMARY KEY,
  "name" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'ACTIVE',
  "created_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_store_friend (
  "merchant_id" TEXT NOT NULL,
  "friend_id" TEXT NOT NULL UNIQUE,
  "created_at" TEXT NOT NULL,
  PRIMARY KEY ("merchant_id", "friend_id")
);

CREATE INDEX IF NOT EXISTS idx_c_merchant_store_friend_merchant
    ON __SCHEMA__.c_merchant_store_friend ("merchant_id");

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_member (
  "account_id" INTEGER PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "role" TEXT NOT NULL DEFAULT 'owner',
  "created_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_policy (
  "merchant_id" TEXT PRIMARY KEY,
  "allowed_actions_json" TEXT NOT NULL DEFAULT '[]',
  "compensation_max_amount" NUMERIC(12,2) NOT NULL DEFAULT 50,
  "refund_max_amount" NUMERIC(12,2) NOT NULL DEFAULT 1000,
  "require_note" INTEGER NOT NULL DEFAULT 0,
  "updated_by" TEXT NOT NULL DEFAULT '',
  "updated_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_policy_audit (
  "policy_audit_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "changed_by" TEXT NOT NULL DEFAULT '',
  "before_json" TEXT NOT NULL DEFAULT '{}',
  "after_json" TEXT NOT NULL DEFAULT '{}',
  "changed_at" TEXT NOT NULL,
  "prev_hash" TEXT NOT NULL DEFAULT '',
  "entry_hash" TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_tenant_provision (
  "provision_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "owner_account_id" INTEGER NOT NULL,
  "created_by" TEXT NOT NULL DEFAULT '',
  "created_at" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.sa_thread (
  "thread_id" TEXT PRIMARY KEY,
  "channel" TEXT NOT NULL,
  "thread_key" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'OPEN',
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "merchant_id" TEXT NOT NULL DEFAULT 'm_gear_002'
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.sa_trigger (
  "trigger_id" TEXT PRIMARY KEY,
  "thread_id" TEXT NOT NULL,
  "source" TEXT NOT NULL,
  "channel" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "metadata_json" TEXT NOT NULL DEFAULT '{}',
  "status" TEXT NOT NULL DEFAULT 'ACCEPTED',
  "created_at" TEXT NOT NULL,
  "processed_at" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.sa_work_item (
  "work_item_id" TEXT PRIMARY KEY,
  "thread_id" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "started_at" TEXT,
  "finished_at" TEXT,
  "result_json" TEXT NOT NULL DEFAULT '{}',
  "error" TEXT,
  "approval_status" TEXT NOT NULL DEFAULT 'NONE',
  "merchant_id" TEXT NOT NULL DEFAULT 'm_gear_002'
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.sa_approval (
  "approval_id" TEXT PRIMARY KEY,
  "work_item_id" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "note" TEXT,
  "created_at" TEXT NOT NULL,
  "decided_at" TEXT,
  "action_json" TEXT NOT NULL DEFAULT '{}',
  "execution_status" TEXT NOT NULL DEFAULT 'NONE',
  "execution_result_json" TEXT NOT NULL DEFAULT '{}',
  "executed_at" TEXT,
  "idempotency_key" TEXT,
  "card_send_response_code" TEXT,
  "card_event_response_code" TEXT
);

CREATE TABLE IF NOT EXISTS __SCHEMA__.sa_job (
  "job_id" TEXT PRIMARY KEY,
  "work_item_id" TEXT NOT NULL,
  "kind" TEXT NOT NULL DEFAULT 'WORKER',
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "attempts" INTEGER NOT NULL DEFAULT 0,
  "max_attempts" INTEGER NOT NULL DEFAULT 2,
  "available_at" TEXT NOT NULL,
  "lease_until" TEXT,
  "worker_id" TEXT,
  "last_error" TEXT,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_c_after_sale_open
    ON __SCHEMA__.c_after_sale (order_id) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_c_after_sale_order
    ON __SCHEMA__.c_after_sale (order_id, created_at);
CREATE INDEX IF NOT EXISTS idx_c_message_owner_friend
    ON __SCHEMA__.c_message (owner_id, friend_id, created_at);
CREATE INDEX IF NOT EXISTS idx_c_app_message_owner_thread
    ON __SCHEMA__.c_app_message (owner_id, thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_c_group_message_owner_group
    ON __SCHEMA__.c_group_message (owner_id, group_id, created_at);
CREATE INDEX IF NOT EXISTS idx_c_friend_request_owner_status
    ON __SCHEMA__.c_friend_request (owner_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_c_group_notice_owner_status
    ON __SCHEMA__.c_group_notice (owner_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_c_mention_owner_target
    ON __SCHEMA__.c_mention (owner_id, target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_c_reconciliation_started
    ON __SCHEMA__.c_reconciliation_run (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_c_reconciliation_alert_open
    ON __SCHEMA__.c_reconciliation_alert (resolved_at, read_at, last_seen_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_thread_key
    ON __SCHEMA__.sa_thread (thread_key);
CREATE INDEX IF NOT EXISTS idx_sa_trigger_thread
    ON __SCHEMA__.sa_trigger (thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sa_work_item_status
    ON __SCHEMA__.sa_work_item (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_approval_work_item
    ON __SCHEMA__.sa_approval (work_item_id);
CREATE INDEX IF NOT EXISTS idx_sa_job_claim
    ON __SCHEMA__.sa_job (status, available_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_job_work_item
    ON __SCHEMA__.sa_job (work_item_id, kind);

ALTER TABLE __SCHEMA__.c_merchant_policy_audit
    ADD COLUMN IF NOT EXISTS "prev_hash" TEXT NOT NULL DEFAULT '';
ALTER TABLE __SCHEMA__.c_merchant_policy_audit
    ADD COLUMN IF NOT EXISTS "entry_hash" TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_policy_audit_anchor (
  "anchor_id" TEXT PRIMARY KEY,
  "merchant_id" TEXT NOT NULL,
  "checked" INTEGER NOT NULL,
  "head_hash" TEXT NOT NULL,
  "created_at" TEXT NOT NULL,
  "prev_anchor_hash" TEXT NOT NULL DEFAULT '',
  "anchor_hash" TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_policy_audit_anchor_merchant
    ON __SCHEMA__.c_policy_audit_anchor (merchant_id, created_at);

CREATE OR REPLACE FUNCTION __SCHEMA__.c_policy_audit_anchor_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'c_policy_audit_anchor is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_c_policy_audit_anchor_no_update
    ON __SCHEMA__.c_policy_audit_anchor;
CREATE TRIGGER trg_c_policy_audit_anchor_no_update
    BEFORE UPDATE ON __SCHEMA__.c_policy_audit_anchor
    FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.c_policy_audit_anchor_append_only();

DROP TRIGGER IF EXISTS trg_c_policy_audit_anchor_no_delete
    ON __SCHEMA__.c_policy_audit_anchor;
CREATE TRIGGER trg_c_policy_audit_anchor_no_delete
    BEFORE DELETE ON __SCHEMA__.c_policy_audit_anchor
    FOR EACH ROW EXECUTE FUNCTION __SCHEMA__.c_policy_audit_anchor_append_only();

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_login_attempt (
  "attempt_key" TEXT PRIMARY KEY,
  "window_start" DOUBLE PRECISION NOT NULL,
  "attempts" INTEGER NOT NULL DEFAULT 0,
  "updated_at" DOUBLE PRECISION NOT NULL
);
