-- P0.6 — resource tuning for a memory-constrained host.
-- Applied via ALTER SYSTEM (writes postgresql.auto.conf) rather than a config
-- file, because the timescaledb-ha image manages postgresql.conf itself.
-- Sized for the 1.5 GiB container limit. Raise after the P0.4 audit is approved.
ALTER SYSTEM SET shared_buffers            = '512MB';
ALTER SYSTEM SET effective_cache_size      = '1536MB';
ALTER SYSTEM SET work_mem                  = '16MB';
ALTER SYSTEM SET maintenance_work_mem      = '128MB';
ALTER SYSTEM SET max_connections           = '20';
ALTER SYSTEM SET timescaledb.telemetry_level = 'off';
ALTER SYSTEM SET random_page_cost          = '1.1';   -- SSD
ALTER SYSTEM SET effective_io_concurrency  = '200';
ALTER SYSTEM SET max_worker_processes      = '8';
ALTER SYSTEM SET max_parallel_workers      = '4';
ALTER SYSTEM SET max_parallel_workers_per_gather = '2';
ALTER SYSTEM SET jit                       = 'off';   -- small queries, JIT is overhead
ALTER SYSTEM SET log_min_duration_statement = '2000ms';
