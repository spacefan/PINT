"""tests for different compute TDB method."""
import pint.models.model_builder as mb
import pint.toa as toa
import astropy.units as u
from pint.residuals import resids
import numpy as np
import os, unittest
import test_derivative_utils as tdu
import logging

from pinttestdata import testdir, datadir

os.chdir(datadir)

class TestTDBMethod(unittest.TestCase):
    """Compare delays from the dd model with tempo and PINT"""
    @classmethod
    def setUpClass(self):
        self.tim = 'B1855+09_NANOGrav_9yv1.tim'

    def test_astropy_ephem(self):
        t_astropy = toa.get_TOAs(self.tim, ephem='DE436t')
        t_ephem = toa.get_TOAs(self.tim, ephem='DE436t', tdb_method="ephemeris")
        diff = (t_astropy.table['tdbld']-t_ephem.table['tdbld'])*86400.0
        assert np.all(np.abs(diff) < 5e-9), "Test TDB method, 'astropy' vs " \
                                            "'ephemeris' failed."
