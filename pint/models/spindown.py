"""This module implements a simple spindown model for an isolated pulsar.
"""
# spindown.py
# Defines Spindown timing model class
import numpy
import astropy.units as u
try:
    from astropy.erfa import DAYSEC as SECS_PER_DAY
except ImportError:
    from astropy._erfa import DAYSEC as SECS_PER_DAY
from .parameter import Parameter, MJDParameter
from .timing_model import TimingModel, MissingParameter
from ..phase import *
from ..utils import time_from_mjd_string, time_to_longdouble, str2longdouble

class Spindown(TimingModel):
    """This class provides a simple timing model for an isolated pulsar."""
    def __init__(self):
        super(Spindown, self).__init__()

        self.add_param(Parameter(name="F0",
            units="Hz",
            description="Spin frequency",
            aliases=["F"],
            parse_value=str2longdouble,
            print_value=repr))

        self.add_param(Parameter(name="F1",
            units="Hz/s", value=0.0,
            description="Spin-down rate"))

        self.add_param(MJDParameter(name="TZRMJD",
            description="Reference epoch for phase = 0.0",
            parse_value=lambda x: time_from_mjd_string(x, scale='tdb')))

        self.add_param(MJDParameter(name="PEPOCH",
            description="Reference epoch for spin-down",
            parse_value=lambda x: time_from_mjd_string(x, scale='tdb')))

        self.phase_funcs += [self.simple_spindown_phase,]

    def setup(self):
        super(Spindown, self).setup()
        # Check for required params
        for p in ("F0",):
            if getattr(self, p).value is None:
                raise MissingParameter("Spindown", p)
        # If F1 is set, we need PEPOCH
        if self.F1.value != 0.0:
            if self.PEPOCH.value is None:
                raise MissingParameter("Spindown", "PEPOCH",
                        "PEPOCH is required if F1 is set")

    def simple_spindown_phase(self, toas, delay):
        """Very simple spindown phase function.

        delay is the time delay from the TOA to time of pulse emission
          at the pulsar, in seconds.

        returns an array of phases in long double
        """
        # If TZRMJD is not defined, use the first time as phase reference
        # NOTE, all of this ignores TZRSITE and TZRFRQ for the time being.
        # TODO: TZRMJD should be set by default somewhere in a standard place,
        #       after the TOAs are loaded (RvH -- June 2, 2015)
        # NOTE: Should we be using barycentric arrival times, instead of TDB?
        if self.TZRMJD.value is None:
            self.TZRMJD.value = toas['tdb'][0] - delay[0]*u.s

        toas = toas['tdbld']
        TZRMJD = time_to_longdouble(self.TZRMJD.value)
        dt = (toas - TZRMJD) * SECS_PER_DAY - delay

        # TODO: what timescale should we use for pepoch calculation? Does this even matter?
        dt_pepoch = (time_to_longdouble(self.PEPOCH.value) - TZRMJD) * SECS_PER_DAY
        F0 = self.F0.value
        F1 = self.F1.value
        phase = (F0 + 0.5 * F1 * (dt - 2.0 * dt_pepoch)) * dt
        return phase

    def d_phase_d_F0(self, toas):
        """Calculate the derivative wrt F0"""
        # If TZRMJD is not defined, use the first time as phase reference
        # TODO: TZRMJD should be set by default somewhere in a standard place,
        #       after the TOAs are loaded (RvH -- June 2, 2015)
        # NOTE: Should we be using barycentric arrival times, instead of TDB?
        if self.TZRMJD.value is None:
            self.TZRMJD.value = toas['tdb'][0] - delay[0]*u.s

        # TODO: toas should have units from the table
        tdb = toas['tdbld'].quantity * u.day
        delay = self.delay(toas) * u.s
        TZRMJD = time_to_longdouble(self.TZRMJD.value) * u.day
        dpdF0 = -(tdb - TZRMJD) - delay
        return dpdF0.decompose()

    def d_phase_d_F1(self, toas):
        """Calculate the derivative wrt F1"""
        # If TZRMJD is not defined, use the first time as phase reference
        # TODO: TZRMJD should be set by default somewhere in a standard place,
        #       after the TOAs are loaded (RvH -- June 2, 2015)
        # NOTE: Should we be using barycentric arrival times, instead of TDB?
        if self.TZRMJD.value is None:
            self.TZRMJD.value = toas['tdb'][0] - delay[0]*u.s

        tdb = toas['tdbld'] * u.day
        delay = self.delay(toas) * u.s
        TZRMJD = time_to_longdouble(self.TZRMJD.value) * u.day
        dt = (tdb - TZRMJD) - delay

        # TODO: what timescale should we use for pepoch calculation? Does this even matter?
        dt_pepoch = (time_to_longdouble(self.PEPOCH.value) * u.day - TZRMJD)

        dpdF1 = -0.5 * (dt - 2.0 * dt_pepoch) * dt
        return dpdF1.decompose()
