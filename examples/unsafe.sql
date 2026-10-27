-- Synthetic only; NEVER run against a real database.
DROP TABLE IF EXISTS old_orders CASCADE;
ALTER TABLE customers DROP COLUMN legacy_ref;
UPDATE invoices SET status = 'closed';
DELETE FROM sessions;
BEGIN;
CREATE INDEX CONCURRENTLY idx_orders_state ON orders (state);
COMMIT;
CREATE INDEX idx_invoices_customer ON invoices (customer_id);
TRUNCATE TABLE events;
ALTER TABLE payments ALTER COLUMN amount TYPE numeric(20,2);
