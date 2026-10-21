-- ============================================================================
-- 千客引擎 · PostgreSQL 首次初始化
--
-- 执行时机：docker-entrypoint-initdb.d 只在 pgdata 卷第一次初始化时执行。
-- 如果 pgdata 已经有数据库，本文件不会再次执行；新增数据库请手工执行。
--
-- 创建原因：
--   - vec_db 是 POSTGRES_DB 指定的默认库（demo 数据集）
--   - vec_db_user / vec_db_test 是 config.py 中固定的 user / test 数据集
--   - rag_auth 是账号、会话、Token 钱包等控制面数据库（auth.py）
--   - 每个库都需要 pgvector 扩展
--
-- 企业库 vec_db_ent_<id> 由应用在企业审核通过/首次构建时动态创建，
-- 这里不预建，避免出现一堆空库。
-- ============================================================================

CREATE DATABASE vec_db_user OWNER postgres;
CREATE DATABASE vec_db_test OWNER postgres;
CREATE DATABASE rag_auth OWNER postgres;

-- demo 数据集
\connect vec_db
CREATE EXTENSION IF NOT EXISTS vector;

-- 用户上传数据集
\connect vec_db_user
CREATE EXTENSION IF NOT EXISTS vector;

-- 测试/临时数据集
\connect vec_db_test
CREATE EXTENSION IF NOT EXISTS vector;

-- 控制面库不需要 vector 扩展；账号表由 auth.ensure_schema() 启动时创建
\connect rag_auth
