import urllib2
import redcap
from influxdb import InfluxDBClusterClient
import openfisca_core.simulations
from gpkit import units, Variable, Model
from gpkit.tools.autosweep import autosweep_1d

client = cli.from_DSN('influxdb://usr:pwd@host1:8086')

A = Variable("A", "m**2")
l = Variable("l", "m")
m1 = Model(A**2, [A >= l**2 + units.m**2])
tol1 = 1e-3
bst1 = autosweep_1d(m1, tol1, l, [1, 10], verbosity=0)
print("Solved after %2i passes, cost logtol +/-%.3g" % (bst1.nsols, bst1.tol))