#   Copyright 2021 The PyMC Developers
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
import warnings

from typing import Dict, Optional

import aesara
import aesara.tensor as aet
import numpy as np

from scipy import optimize

import pymc as pm

__all__ = ["find_optim_prior"]


def find_optim_prior(
    pm_dist: pm.Distribution,
    lower: float,
    upper: float,
    init_guess: Dict[str, float],
    mass: float = 0.95,
    fixed_params: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Find optimal parameters to get `mass` % of probability
    of `pm_dist` between `lower` and `upper`.
    Note: only works for one- and two-parameter distributions, as there
    are exactly two constraints. Fix some combination of parameters
    if you want to use it on >=3-parameter distributions.

    Parameters
    ----------
    pm_dist : pm.Distribution
        PyMC distribution you want to set a prior on.
        Needs to have a ``logcdf`` method implemented in PyMC.
    lower : float
        Lower bound to get `mass` % of probability of `pm_dist`.
    upper : float
        Upper bound to get `mass` % of probability of `pm_dist`.
    init_guess: Dict[str, float]
        Initial guess for ``scipy.optimize.least_squares`` to find the
        optimal parameters of `pm_dist` fitting the interval constraint.
        Must be a dictionary with the name of the PyMC distribution's
        parameter as keys and the initial guess as values.
    mass: float, default to 0.95
        Share of the probability mass we want between ``lower`` and ``upper``.
        Defaults to 95%.
    fixed_params: Dict[str, float], Optional, default None
        Only used when `pm_dist` has at least three parameters.
        Dictionary of fixed parameters, so that there are only 2 to optimize.
        For instance, for a StudenT, you fix nu to a constant and get the optimized
        mu and sigma.

    Returns
    -------
    The optimized distribution parameters as a dictionary with the parameters'
    name as key and the optimized value as value.
    """
    if len(init_guess) > 2:
        if (fixed_params is None) or (len(fixed_params) < (len(pm_dist.rv_op.ndims_params) - 2)):
            warnings.warn(
                f"It seems like {pm_dist} has {len(pm_dist.rv_op.ndims_params)} parameters. "
                "Note that `pm.find_optim_prior` can only optimize two parameters, so there may "
                "not be a unique solution in your use-case. "
                f"Consider fixing {len(pm_dist.rv_op.ndims_params) - 2} parameters in the "
                f"`fixed_params` dictionary. "
            )

    dist_params = aet.vector("dist_params")
    params_to_optim = {
        arg_name: dist_params[i] for arg_name, i in zip(init_guess.keys(), range(len(init_guess)))
    }
    lower_, upper_ = aet.scalars("lower", "upper")

    if fixed_params is not None:
        dist_ = pm_dist.dist(**(params_to_optim | fixed_params))
    else:
        dist_ = pm_dist.dist(**params_to_optim)

    try:
        logcdf_lower = pm.logcdf(dist_, lower_)
        logcdf_upper = pm.logcdf(dist_, upper_)
    except AttributeError:
        raise AttributeError(
            f"You cannot use `find_optim_prior` with {pm_dist} -- it doesn't have a logcdf "
            "method yet. Open an issue or, even better, a pull request on PyMC repo if you really "
            "need it."
        )

    out = pm.math.logdiffexp(logcdf_upper, logcdf_lower) - np.log(mass)
    logcdf = aesara.function([dist_params, lower_, upper_], out)

    try:
        symb_grad = aet.as_tensor_variable([pm.gradient(o, [dist_params]) for o in out])
        jac = aesara.function([dist_params, lower_, upper_], symb_grad)

    # when PyMC cannot compute the gradient
    except Exception:
        jac = "2-point"

    opt = optimize.least_squares(logcdf, x0=list(init_guess.values()), jac=jac, args=(lower, upper))
    if not opt.success:
        raise ValueError("Optimization of parameters failed.")

    if fixed_params is not None:
        return {
            param_name: param_value for param_name, param_value in zip(init_guess.keys(), opt.x)
        } | fixed_params
    else:
        return {
            param_name: param_value for param_name, param_value in zip(init_guess.keys(), opt.x)
        }


# tests
# add warning when mass is lower than expected -- try another initial guess?
