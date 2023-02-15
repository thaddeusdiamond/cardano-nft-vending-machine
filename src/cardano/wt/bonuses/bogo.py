import math

"""
Provides the ability to add buy-one-get-one functionality to the vending machine
based on a specified threshold.  For example, a buy-5-get-2-free BOGO would be
represented with Bogo(5, 2).
"""
class Bogo(object):

    def __init__(self, threshold, additional):
        self.threshold = threshold
        self.additional = additional

    def determine_bonuses(self, num_mints_requested):
        return math.floor(num_mints_requested / self.threshold) * self.additional
