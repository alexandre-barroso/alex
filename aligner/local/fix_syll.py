#!/usr/bin/env python3
"""Fill missing syllabification entries by copying the grapheme form."""

import sys
import logging
from collections import OrderedDict

logging.basicConfig(
    format="%(filename)s %(levelname)8s %(message)s",
    level=logging.INFO
)


if __name__ == "__main__":

    # scan lexicon for abbrevs: if it has at least one vowel, it isn't
    # NOTE: partition() doesn't raise if phonemes are null; split() does
    new_dict = OrderedDict()
    for line in sys.stdin:
        graph, _, syllables = line.strip().partition("\t")
        graph, syllables = graph.strip(), syllables.strip()
        if syllables == "":
            logging.debug(f"empty syllables for {graph}. fixing...")
            syllables = graph
        new_dict[graph] = syllables

    # write new lexicon
    for key, value in new_dict.items():
        print(f"{key}\t{value}")
