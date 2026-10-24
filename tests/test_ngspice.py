"""End-to-end checks against an explicitly selected ngspice executable."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from spice_jacobian_check import check
from spice_jacobian_check.cli import main

BINARY=os.environ.get('NGSPICE_BINARY')


@unittest.skipUnless(BINARY,'Set NGSPICE_BINARY for simulator integration tests')
class NgspiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.deck=self.root/'deck.cir'

    def tearDown(self):self.temp.cleanup()

    def evaluate(self,text,step=1e-5,frequency=1e-5):
        self.deck.write_text(text)
        return check(self.deck,'V1','v(out)',.1,step,binary=BINARY,frequency=frequency)

    def test_source_isolation_and_restricted_save_lists(self):
        r=self.evaluate('Divider\nV1 IN 0 DC .1 AC 7\n V2 REF 0 DC .2 AC 4\nR1 IN OUT 1k\nR2 OUT REF 1k\n.save v(ref)\n+ v(in)\n.end\n')
        self.assertEqual(r['status'],'pass');self.assertAlmostEqual(r['ac_real'],.5,places=10)

    def test_dc_step_convergence(self):
        deck='Cubic\nV1 IN 0 .1\nB1 OUT 0 V={v(in)^3}\n.end\n'
        self.assertEqual(self.evaluate(deck,step=.1)['status'],'fail')
        self.assertEqual(self.evaluate(deck)['status'],'pass')

    def test_above_pole_and_invalid_probe_fail(self):
        self.assertEqual(self.evaluate('RC\nV1 IN 0 .1\nR1 IN OUT 1k\nC1 OUT 0 1u\n.end\n',frequency=1e6)['status'],'fail')
        self.assertEqual(self.evaluate('Missing node\nV1 IN 0 .1\nR1 IN 0 1k\n.end\n')['status'],'simulation_error')

    def test_cli_multiple_pairs_and_zero_check_rejection(self):
        self.deck.write_text('Divider\nV1 IN 0 .1\nR1 IN OUT 1k\nR2 OUT 0 1k\n.end\n')
        pairs=self.root/'pairs.json';output=self.root/'results.json'
        pairs.write_text(json.dumps([dict(source='V1',probe='v(out)',bias=.1,step=1e-5),dict(source='V1',probe='i(v1)',bias=.1,step=1e-5)]))
        self.assertEqual(main(['check',str(self.deck),'--pairs',str(pairs),'--ngspice',BINARY,'--output',str(output)]),0)
        self.assertEqual(json.loads(output.read_text())['executed'],2)
        pairs.write_text('[]')
        with self.assertRaises(SystemExit) as caught:main(['check',str(self.deck),'--pairs',str(pairs),'--ngspice',BINARY])
        self.assertEqual(caught.exception.code,2)


if __name__=='__main__':unittest.main()
