"""Kept as a no-op (decision 2026-11-27): Cost Type 'Country Specific-Currency' is a valid option again.

This patch used to rewrite 'Country Specific-Currency' to 'Country Specific', because the field listed only
Country Specific and % of UAE and such rows could not be saved. The field now lists all three values
(Country Specific, Country Specific-Currency, % of UAE), so the rows keep what they say. The patch stays in
patches.txt so sites that ran it and sites that haven't share one patch list.
"""


def execute():
	print("FTOCountryWiseCost: Cost Type 'Country Specific-Currency' is an option again - no rows changed")
