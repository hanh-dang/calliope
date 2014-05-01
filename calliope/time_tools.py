"""
Copyright (C) 2013 Stefan Pfenninger.
Licensed under the Apache 2.0 License (see LICENSE file).

time_tools.py
~~~~~~~~~~~~~

Provides the TimeSummarizer class to dynamically adjust time resolution.

"""

from __future__ import print_function
from __future__ import division

import numpy as np
import pandas as pd

from . import time_masks
from . import utils


class TimeSummarizer(object):
    """
    Provides methods to reduce time resolution for the given model data.

    """
    def __init__(self):
        super(TimeSummarizer, self).__init__()
        # Format: {'data item': 'method'}
        self.known_data_types = {'_t': self._reduce_cut,
                                 '_dt': self._reduce_cut,
                                 'a': self._reduce_r_to_a,
                                 'r': self._reduce_sum,
                                 'r_eff': self._reduce_average,
                                 'e_eff': self._reduce_average}
        self.source_parameters = {'a': 'r'}

    def _apply_method(self, data, method, s, param, src_param=None,
                      subkey=None):
        i = data['_t'].iat[s.start]
        if not src_param:
            src_param = param
        if subkey:
            data[param][subkey].loc[i] = method(data[src_param][subkey][s])
        else:
            data[param].at[i] = method(data[src_param][s])

    def _reduce_resolution(self, data, resolution, t_range):
        """Helper function called by dynamic_timestepper."""
        # Initialize some common data
        resolution = resolution / data.time_res_data
        assert resolution.is_integer()
        resolution = int(resolution)
        self.resolution = resolution
        # Set up time range slice
        s = slice(*t_range)
        # Go through each item in data and apply the appropriate method to it
        for k in data.keys():
            if k in self.known_data_types.keys():
                how = self.known_data_types[k]
                if k in self.source_parameters:
                    src = self.source_parameters[k]
                else:
                    src = None
                if isinstance(data[k], utils.AttrDict):
                    for kk in data[k].keys():
                        self._apply_method(data, how, s, param=k,
                                           src_param=src, subkey=kk)
                else:
                    self._apply_method(data, how, s, param=k,
                                       src_param=src)

    def dynamic_timestepper(self, data, mask):
        """``mask`` must be a series with the same index as the given data.

        For each timestep, the ``mask`` can either be 0 (no
        adjustment), >0 (marks the first timestep to be compressed, with
        the integer value giving the number of timesteps to compress) or
        -1 (marks timesteps following a >0 timestep that will be compressed).

        For example, ``mask`` could contain::

            [0, 0, 0, 3, -1, -1, 0, 0, 2, -1, 2, -1]

        This would result in data with the following new timestep resolution::

            [1, 1, 1, 3, 1, 1, 2, 2]

        Warning: modifies the passed data object in-place.
        Returns None on success.

        """
        df = pd.DataFrame(mask, index=mask.index)
        df.columns = ['summarize']  # rename the single column
        df['time_res'] = data.time_res_static
        df['to_keep'] = True
        # Get all time steps that need summarizing
        entry_points = df.summarize[df.summarize > 0]
        # 1. Summarize by calling _reduce_resolution for the desired ranges
        # This step still keeps the summarized data but marks it by setting
        # `to_keep` to False
        for i, v in entry_points.iteritems():
            ifrom = i
            ito = i + int(v / data.time_res_static)
            resolution = v
            self._reduce_resolution(data, resolution, t_range=[ifrom, ito])
            # Mark the rows that need to be killed with False
            df.to_keep.iloc[ifrom+1:ito] = False
            df.time_res.iloc[ifrom] = resolution
        # 2. Replace all data with its subset where to_keep is True
        for k in data.keys():
            # # Special case for `_t`, which is the only known_data_type which is always 0-indexed
            # if k == '_t' or k == '_dt':
            #     # To get around non-matching index, we simply turn the boolean mask df into a list
            #     data[k] = data[k][(df.summarize < 2).tolist()]
            if k in self.known_data_types.keys():
                if isinstance(data[k], utils.AttrDict):
                    for kk in data[k].keys():
                        data[k][kk] = data[k][kk][df.to_keep]
                else:
                    data[k] = data[k][df.to_keep]
            # TODO else: log that there was a data item of unknown type
        data.time_res_series = df.time_res[df.to_keep]
        # NB data.time_res_static is not adjusted here, but this should be ok

    def reduce_resolution(self, data, resolution):
        """
        Reduces the resolution of the entire ``data`` to ``resolution``,
        which must be an integer and greater than the initial resolution.

        Modifies the passed data object in-place and returns None.

        """
        mask = time_masks.resolution_series_uniform(data, resolution)
        self.dynamic_timestepper(data, mask)
        data.time_res_static = resolution

    def _reduce_average(self, df):
        return df.mean(0)

    def _reduce_sum(self, df):
        return df.sum(0)

    def _reduce_cut(self, df):
        return df.iloc[0]

    def _reduce_r_to_a(self, df):
        """
        Based on resource data given in ``df``, generate availability data

        """
        if (df.sum(axis=0) == np.inf).all():
            # If the df is all infinite, availability is 1
            result = 1
        elif df.max().max() == 0 and df.min().min() == 0:
            # And if it's all zero, availability is 0
            result = 0
        else:
            result = df.sum() / (df.max() * len(df))
            result = result.fillna(0)  # Fill NaNs from division by zero
        return result
