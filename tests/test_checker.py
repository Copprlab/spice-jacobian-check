"""Tool safeguards, independent of a particular simulator installation."""
from pathlib import Path
import tempfile
import unittest

from spice_jacobian_check.checker import assess, check, circuit, independent_sources, validate
from spice_jacobian_check.ngspice import Simulation


def scalars(**overrides):
    values=dict(zero=.15, plus=.150005, minus=.149995, half_plus=.1500025,
                half_minus=.1499975, **{'return':.15})
    for i in range(3):values.update({f're{i}':.5,f'im{i}':0})
    values.update(overrides)
    return '\n'.join(f'sjc_{key} = {value}' for key,value in values.items())


class CheckerTests(unittest.TestCase):
    def test_missing_nonfinite_and_exit_error_cannot_pass(self):
        for log,code in [(scalars(re1='nan'),0),(scalars().replace('sjc_plus','removed'),0),(scalars(),1)]:
            self.assertEqual(assess(log,code,1e-5,1e-5,1e-4,1e-8)['status'],'simulation_error')

    def test_transient_fallback_is_invalid_even_with_matching_slopes(self):
        self.assertEqual(assess(scalars()+'\nNote: Transient op started',0,1e-5,1e-5,1e-4,1e-8)['status'],'invalid_operating_point')

    def test_dc_branch_must_return_to_same_nominal_point(self):
        self.assertEqual(assess(scalars(**{'return':.2}),0,1e-5,1e-5,1e-4,1e-8)['status'],'invalid_operating_point')

    def test_deck_materialization_preserves_model_continuations(self):
        text='Title\n.model M D(IS=1e-14\n+ N=2)\n.save v(a)\n+ v(b)\n.control\nalter R1=2\n.endc\n.end\n'
        self.assertEqual(circuit(text),'Title\n.model M D(IS=1e-14\n+ N=2)')

    def test_nested_subcircuits_are_not_top_level_sources(self):
        text='Title\nV1 A 0 1\n.subckt X A\n.subckt Y B\nV2 B 0 2\n.ends Y\nV3 A 0 3\n.ends X\n I4 0 A 0\n'
        self.assertEqual(list(independent_sources(text)),['V1','I4'])

    def test_bad_and_unresolved_steps_are_rejected(self):
        for step in [0,-1,float('nan'),1e-30]:
            with self.assertRaises(ValueError):validate('V1','v(out)',1,step,1e-5,1e-4,1e-8)

    def test_adapter_boundary_and_temporary_cleanup(self):
        class Adapter:
            def run(self,deck,cwd):
                self.path=deck
                self.text=deck.read_text()
                return Simulation(0,scalars())
        adapter=Adapter()
        with tempfile.TemporaryDirectory() as folder:
            deck=Path(folder)/'input.cir';deck.write_text('Divider\nV1 A 0 .1\nR1 A OUT 1k\n.end\n')
            result=check(deck,'V1','v(out)',.1,1e-5,adapter=adapter)
            self.assertEqual(result['status'],'pass')
            self.assertFalse(adapter.path.exists())
            self.assertIn('alter @V1[acmag] = 1',adapter.text)
            self.assertNotIn('work_directory',result)


if __name__=='__main__':unittest.main()
