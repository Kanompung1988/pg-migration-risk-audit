import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit', ROOT/'scripts/audit.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def rules(sql): return {x['rule'] for x in audit.audit_text(sql,'migration.sql')}


class SQLMaskTests(unittest.TestCase):
    def test_single_quote_masks_keywords(self): self.assertNotIn('PG001',rules("SELECT 'DROP TABLE x;';"))
    def test_doubled_quote(self): self.assertNotIn('PG001',rules("SELECT 'it''s a DROP TABLE x;';"))
    def test_double_quote(self): self.assertNotIn('PG001',rules('SELECT "DROP TABLE fake;";'))
    def test_line_comments(self): self.assertEqual(rules('-- DROP TABLE x;\nSELECT 1;'),set())
    def test_nested_block_comments(self): self.assertEqual(rules('/* outer /* inner */ DROP TABLE x */ SELECT 1;'),set())
    def test_dollar_quoted(self): self.assertEqual(rules('SELECT $$ DROP TABLE x; $$;'),set())
    def test_tagged_dollar_quoted(self): self.assertEqual(rules('DO $body$ DROP TABLE x; $body$;'),set())
    def test_unclosed_literal(self):
        with self.assertRaises(audit.InputError): audit.audit_text("SELECT 'oops",'x.sql')
    def test_unclosed_comment(self):
        with self.assertRaises(audit.InputError): audit.audit_text('/*', 'x.sql')
    def test_line_positions(self): self.assertEqual(audit.audit_text('\n-- note\nDROP TABLE t;','x.sql')[0]['line'],3)


class RiskRulesTests(unittest.TestCase):
    def test_drop_table(self): self.assertIn('PG001',rules('DROP TABLE t;'))
    def test_drop_schema(self): self.assertIn('PG001',rules('DROP SCHEMA public;'))
    def test_drop_column(self): self.assertIn('PG002',rules('ALTER TABLE t DROP COLUMN a;'))
    def test_drop_constraint(self): self.assertIn('PG002',rules('ALTER TABLE t DROP CONSTRAINT fk;'))
    def test_truncate(self): self.assertIn('PG003',rules('TRUNCATE t;'))
    def test_update_no_where(self): self.assertIn('PG004',rules('UPDATE t SET a=1;'))
    def test_delete_no_where(self): self.assertIn('PG004',rules('DELETE FROM t;'))
    def test_update_where(self): self.assertNotIn('PG004',rules('UPDATE t SET a=1 WHERE id=5;'))
    def test_index_blocking(self): self.assertIn('PG005',rules('CREATE UNIQUE INDEX idx ON t (id);'))
    def test_concurrently_no_transaction(self): self.assertNotIn('PG006',rules('CREATE INDEX CONCURRENTLY idx ON t(id);'))
    def test_concurrently_in_tx(self): self.assertIn('PG006',rules('BEGIN; CREATE INDEX CONCURRENTLY idx ON t(id); COMMIT;'))
    def test_concurrently_after_commit(self): self.assertNotIn('PG006',rules('BEGIN; SELECT 1; COMMIT; CREATE INDEX CONCURRENTLY idx ON t(id);'))
    def test_alter_type(self): self.assertIn('PG007',rules('ALTER TABLE t ALTER COLUMN c TYPE text;'))
    def test_cascade(self): self.assertIn('PG008',rules('DROP TABLE t CASCADE;'))
    def test_lit_where_not_masked_as_clause(self): self.assertIn('PG004',rules("UPDATE t SET a='WHERE';"))
    def test_safe_fixture_has_no_findings(self): self.assertEqual(audit.scan(ROOT/'examples/safe.sql'),[])


class GuardTests(unittest.TestCase):
    def test_cli_nonzero_high(self):
        p=subprocess.run([sys.executable,str(ROOT/'scripts/audit.py'),str(ROOT/'examples/unsafe.sql'), '--format','json'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertGreater(json.loads(p.stdout)['count'],4)
    def test_cli_json_none(self):
        p=subprocess.run([sys.executable,str(ROOT/'scripts/audit.py'),str(ROOT/'examples/unsafe.sql'), '--format','json','--fail-on','none'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0)
    def test_missing_input(self): self.assertEqual(audit.main(['/no/such/file.sql']),1)
    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'link.sql';p.symlink_to(ROOT/'examples/unsafe.sql')
            with self.assertRaises(audit.InputError): audit.scan(p)
    def test_oversized_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'big.sql';p.write_text('x'*(audit.MAX_BYTES+1))
            with self.assertRaises(audit.InputError): audit.scan(p)
    def test_recursive_scan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'migration';p.mkdir();(p/'up.sql').write_text('DROP TABLE t;')
            self.assertEqual(len(audit.scan(Path(d))),1)
    def test_hidden_directories_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.git';p.mkdir();(p/'unsafe.sql').write_text('DROP TABLE t;')
            self.assertEqual(audit.scan(Path(d)),[])

if __name__=='__main__': unittest.main()
