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
  "product_refs_json" TEXT NOT NULL,
  "policy_refs_json" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'PENDING',
  "created_at" TEXT NOT NULL
);

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
  "user_avatar_path" TEXT NOT NULL DEFAULT ''
);

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

CREATE TABLE IF NOT EXISTS __SCHEMA__.c_merchant_tenant (
  "merchant_id" TEXT PRIMARY KEY,
  "name" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'ACTIVE',
  "created_at" TEXT NOT NULL
);

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
  "changed_at" TEXT NOT NULL
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
