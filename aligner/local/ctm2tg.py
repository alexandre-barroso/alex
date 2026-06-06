#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert alignment CTM output to IPA-normalized TextGrid files."""

import argparse
import logging
import os
import re
import unicodedata
from collections import OrderedDict
from typing import Dict, List, Tuple, Optional, Union

import pandas as pd
from textgrid import TextGrid, IntervalTier


PHONE_TO_IPA = {
    "<eps>": "",
    "sil": "",
    "a": "a",
    "a~": "ã",
    "b": "b",
    "d": "d",
    "dZ": "dʒ",
    "e": "e",
    "e~": "ẽ",
    "E": "ɛ",
    "f": "f",
    "g": "ɡ",
    "i": "i",
    "i~": "ĩ",
    "j": "j",
    "j~": "j̃",
    "J": "ɲ",
    "k": "k",
    "l": "l",
    "L": "ʎ",
    "m": "m",
    "n": "n",
    "o": "o",
    "o~": "õ",
    "O": "ɔ",
    "p": "p",
    "r": "ɾ",
    "R": "ʁ",
    "s": "s",
    "S": "ʃ",
    "t": "t",
    "tS": "tʃ",
    "u": "u",
    "u~": "ũ",
    "v": "v",
    "w": "w",
    "w~": "w̃",
    "X": "χ",
    "z": "z",
    "Z": "ʒ",
}
UNKNOWN_IPA_TOKENS = set()
BLANK_LABELS = {"<eps>", "eps", "sil"}


def get_args():
    parser = argparse.ArgumentParser()
    # https://stackoverflow.com/questions/14097061/easier-way-to-enable-verbose-logging
    parser.add_argument(
        "-d", "--debug", action="store_const", dest="loglevel",
        const=logging.DEBUG, default=logging.INFO,
        help="log more"
    )
    parser.add_argument(
        "-g", "--graphemes-ctm-file", type=str, required=True,
        help="something like 'mono.graphemes.ctm'"
    )
    parser.add_argument(
        "-p", "--phonemes-ctm-file", type=str, required=True,
        help="something like 'mono.phonemes.ctm'"
    )
    parser.add_argument(
        "-l", "--phonetic-dictionary", type=str, required=True,
        help="something like 'lexicon.txt'"
    )
    parser.add_argument(
        "-s", "--syllphones-dictionary", type=str, required=True,
        help="something like 'syllphones.txt'"
    )
    #parser.add_argument(
    #    "-i", "--ignore-syllphones", action="store_true",
    #    help="whether to build the syllphones tier"
    #)
    parser.add_argument(
        "-o", "--output-dir", type=str, required=True,
        help="directory to dump TextGrid files"
    )
    return parser.parse_args()


# https://stackoverflow.com/questions/2507808/how-to-check-whether-a-file-is-empty-or-not
def check_ctm(filename: str) -> None:
    if not os.path.isfile(filename):
        raise ValueError(f"{filename} does not exist")
    if not filename.endswith(".ctm"):
        raise ValueError(f"{filename} doesn't have a *.ctm extension")
    if not os.stat(filename).st_size:
        raise ValueError(f"{filename} appears to be empty")
    logging.debug(f"{filename} is juicy good!")


# https://stackoverflow.com/questions/13479163/round-float-to-x-decimals (#16)
def floatify(val: Union[str, float]) -> float:
    """Convert a string or float to a special kind of float.

    The idea is having only two decimals, and some special rules are applied
    to strings based on observations on how the speech engine provides the float numbers
    in timestamps.

    Args:
        val: string or float to be floatified
    Returns:
        A two-decimal floating point timestamp
    """
    if isinstance(val, float):
        return round(float(val), 2)
    if val.endswith("0"):
        return float(val)
    if val.endswith("5"):
        return float(val) - 0.005
    return round(float(val), 2)


# ctm2tg.py    DEBUG phonemes i=7293 bos=754.24 eos=754.34 a_E
# ctm2tg.py    DEBUG phonemes i=7294 bos=754.34 eos=754.38 k_B
# ctm2tg.py    DEBUG phonemes i=7295 bos=754.37 eos=754.44 o_I
# Traceback (most recent call last):
def compute_eos_and_ensure_causality(
    bos: List[float],
    dur: List[float],
    tokens: List[str]
) -> Tuple[List[float], List[float]]:
    """Compute EOS values and fix BOS in order to ensure causality.

    Some tools apply sanity checks over Textgrid files like asserting
    whether the current phone's BOS is smaller than the previous phone's EOS.
    Due to numerical precision problems, the speech engine cannot always assert that, and
    apparently parameter tweaking is no help, which only leave us with the
    option of changing the C++ code and recompiling the binaries, which for
    now is infeasible.

    Args:
        bos: list of beginning of speech floating point timestamps, from CTM
        dur: list of durations of each phone, from CTM
        tokens: phone symbols
    Returns:
        A tuple with fixed bos and new eos, which is the sum of bos and dur
    """
    assert len(bos) == len(dur)
    eos = [floatify(b + d) for b, d in zip(bos, dur)]
    for i in range(1, len(bos)):
        prev_bos, curr_bos = bos[i-1], bos[i]
        prev_eos, curr_eos = eos[i-1], eos[i]
        prev_tok, curr_tok = tokens[i-1], tokens[i]
        if curr_bos < prev_eos:
            logging.warning(
                f"causality problem at frame {i=}: "
                f"{prev_bos=:.2f} {prev_eos=:.2f} {prev_tok:4s} | "
                f"{curr_bos=:.2f} {curr_eos=:.2f} {curr_tok:4s}"
            )
            bos[i] = prev_eos
    return bos, eos


def senone_to_monophone(senone: str) -> str:
    """Convert senone symbols to monophone symbols.

    Senones are basically the monophones with beginning, ending or intermediate
    markers. This function basically gets rid of the markers.

    Args:
        senone: a string representing the senone symbol
    Returns:
        A string representing the monophone symbol
    """
    return re.sub(r"_[BIES]$", "", senone)


def clean_textgrid_mark(mark: str) -> str:
    """Normalize TextGrid labels to lowercase text without punctuation."""
    if str(mark).strip().casefold() in BLANK_LABELS:
        return ""
    cleaned = []
    for char in str(mark).casefold():
        category = unicodedata.category(char)
        if char.isspace():
            cleaned.append(" ")
        elif category[0] in ("P", "S", "C"):
            cleaned.append(" ")
        else:
            cleaned.append(char)
    return re.sub(r"\s+", " ", "".join(cleaned)).strip()


def phone_to_ipa(phone: str) -> str:
    phone = senone_to_monophone(str(phone))
    try:
        return PHONE_TO_IPA[phone]
    except KeyError:
        if phone not in UNKNOWN_IPA_TOKENS:
            logging.warning("no IPA mapping for phone symbol %r; keeping it", phone)
            UNKNOWN_IPA_TOKENS.add(phone)
        return phone


def phone_sequence_to_ipa(sequence: str, join_tokens: bool = False) -> str:
    ipa_tokens = []
    for token in str(sequence).split():
        ipa = phone_to_ipa(token)
        if ipa:
            ipa_tokens.append(ipa)
    separator = "" if join_tokens else " "
    return separator.join(ipa_tokens)


# NOTE load bos as a string and force fit it as a float later when requested
def load_ctm(filename: str) -> pd.DataFrame:
    """Loads a CTM file from disk into a DataFrame in memory.

    Args:
        filename: name of the ctm file to load from disk
    Returns:
        A pandas DataFrame with four columns: uttid, bos, eos, and token
    """
    logging.info(f"loading {filename} ...")
    check_ctm(filename)
    ctm = pd.read_csv(
        filename, sep=" ", #engine="python",
        names=["uttid", "chid", "bos", "dur", "token"],
        dtype={"uttid": str, "chid": str, "bos": str, "dur": float, "token": str},
    )
    logging.debug(ctm.head(10))
    ctm["token"] = ctm["token"].apply(lambda x: senone_to_monophone(x))
    ctm["bos"] = ctm["bos"].apply(lambda x: floatify(x))
    ctm["dur"] = ctm["dur"].apply(lambda x: floatify(x))
    chunks = []
    for _, utt_df in ctm.groupby("uttid", sort=False):
        utt_df = utt_df.copy()
        utt_df["bos"], utt_df["eos"] = compute_eos_and_ensure_causality(
            utt_df["bos"].tolist(), utt_df["dur"].tolist(), utt_df["token"].tolist()
        )
        chunks.append(utt_df)
    ctm = pd.concat(chunks, ignore_index=True) if chunks else ctm
    ctm = ctm.drop(["dur", "chid"], axis=1)
    ctm = ctm.reindex(["uttid", "bos", "eos", "token"], axis=1)
    logging.debug(ctm.head(10))
    return ctm


# https://stackoverflow.com/questions/18695605/how-to-convert-a-dataframe-to-a-dictionary
def load_dictionary(filename: str) -> Dict[str, str]:
    """Load tab-sep phonetic or syllabic dictionaries

    Args:
        filename: name of the two-column file to load from disk
    Returns:
        A dict with grapheme words as keys and tokens as values
    """
    logging.info(f"loading {filename} ...")
    dictionary = pd.read_csv(
        filename, sep="\t", engine="python", names=["word", "tokens"],
    )
    dictionary["word"] = dictionary["word"].apply(clean_textgrid_mark)
    return OrderedDict(zip(dictionary["word"], dictionary["tokens"]))


def join_tokens_as_a_sentence(
    tokens: List[str],
    lexicon: Optional[Dict[str, str]] = None,
) -> str:
    """Join tokens that belong to the same word, discarding silences.

    This is useful for some tiers that comprise the full sentence that has been
    aligned, either as graphemes or phonemes.

    Args:
        tokens: A list of string tokens, which can be either phonemes or
        syllphones
        lexicon: A dictionary that maps graphemes to the respective
        aforementioned token
    Returns:
        A string containing the tokens from the list separated by white space
    """
    sent = []
    for t in tokens:
        if t in ("<eps>", "sil"):
            continue
        if lexicon:
            key = t if t in lexicon else clean_textgrid_mark(t)
            if key in lexicon:
                sent.append(phone_sequence_to_ipa(lexicon[key], join_tokens=True))
            else:
                logging.warning("no lexicon entry for token %r; keeping cleaned token", t)
                sent.append(key)
        else:
            sent.append(t)
    return " ".join(sent).strip()


def build_syllphones_ctm(
    p_ctm: pd.DataFrame,
    g_ctm: pd.DataFrame,
    sp_dict: Dict[str, str],
    p_dict: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Build a syllable-phone tier from word and phone CTM intervals.

    Args:
        p_ctm: A DataFrame containing info from the phonemes CTM file
        g_ctm: A DataFrame containing info from the graphemes CTM file
        sp_dict: A dictionary that maps graphemes to phonemes
        p_dict: A dictionary that maps graphemes to syllphones
    Returns:
        A pandas DataFrame with info regarding the syllphones CTM
    """
    df_list = []
    for uttid in g_ctm["uttid"].unique():
        try:
            w_df = g_ctm[g_ctm["uttid"] == uttid]
            p_df = p_ctm[p_ctm["uttid"] == uttid]
            ctm = []
            prev_bos = 0.0
            for word in w_df['token']:
                key = word if word in sp_dict else clean_textgrid_mark(word)
                logging.debug(f"fetching syllphones for {word=}")
                try:
                    syllphones = sp_dict[key]
                except KeyError:
                    logging.error(
                        f"{uttid=} {word=} not in syllphones. retrieving as-is from lexicon"
                    )
                    syllphones = p_dict[key]
                logging.debug(f"{syllphones=}")
                for syllable in [s.strip() for s in syllphones.split('-')]:
                    last_phone = syllable.split()[-1]
                    logging.debug(f"fetching times for {last_phone=}")
                    # NOTE the bos condition looks brittle. keep an eye on that.
                    candidates = p_df[
                        (p_df['token'] == last_phone) & (p_df['bos'] >= prev_bos)
                    ]['eos'].tolist()
                    if not candidates:
                        raise ValueError(
                            f"no phone timing for {uttid=} {word=} {last_phone=} after {prev_bos=}"
                        )
                    eos = candidates[0]
                    ctm.append((uttid, prev_bos, eos, syllable))
                    prev_bos = eos
            df = pd.DataFrame(ctm, columns=["uttid", "bos", "eos", "token"])
            df_list.append(df)
        except Exception as exc:
            logging.exception("could not build syllable tier for %s; continuing without it: %s", uttid, exc)
    return (
        pd.concat(df_list, ignore_index=True)
        if df_list
        else pd.DataFrame(columns=["uttid", "bos", "eos", "token"])
    )


def main(args):
    g_ctm = load_ctm(args.graphemes_ctm_file)
    p_ctm = load_ctm(args.phonemes_ctm_file)
    lexicon = load_dictionary(args.phonetic_dictionary)

    syllphones = load_dictionary(args.syllphones_dictionary)
    s_ctm = build_syllphones_ctm(p_ctm, g_ctm, syllphones, p_dict=lexicon)

    os.makedirs(args.output_dir, exist_ok=True)
    for uttid in g_ctm["uttid"].unique():
        try:
            w_df = g_ctm[g_ctm["uttid"] == uttid]
            p_df = p_ctm[p_ctm["uttid"] == uttid]
            s_df = s_ctm[s_ctm["uttid"] == uttid]
            if w_df.empty or p_df.empty:
                raise ValueError(f"empty CTM tier for {uttid=}")
            # build canonical phonemes tier
            logging.info("building 'phonemes' tier...")
            p_tier = IntervalTier(name="phonemes")
            for i, (t, bos, eos) in enumerate(
                zip(p_df["token"], p_df["bos"], p_df["eos"])
            ):
                mark = phone_to_ipa(t)
                logging.debug(f"phonemes {i=} {bos=} {eos=} {t} {mark=}")
                p_tier.add(minTime=bos, maxTime=eos, mark=clean_textgrid_mark(mark))
            # build canonical words tier
            logging.info("building 'words' tier...")
            w_tier = IntervalTier(name="words")
            for t, bos, eos in zip(w_df["token"], w_df["bos"], w_df["eos"]):
                w_tier.add(minTime=bos, maxTime=eos, mark=clean_textgrid_mark(t))
            # build canonical syllables tier
            logging.info("building 'syllables' tier...")
            s_tier = IntervalTier(name="syllables")
            for t, bos, eos in zip(s_df["token"], s_df["bos"], s_df["eos"]):
                mark = phone_sequence_to_ipa(t)
                s_tier.add(minTime=bos, maxTime=eos, mark=clean_textgrid_mark(mark))
            # build canonical utterance tier
            logging.info("building 'utterance' tier...")
            gs_tier = IntervalTier(name="utterance")
            bos = sorted(w_df["bos"].tolist())[0]
            eos = sorted(w_df["eos"].tolist())[-1]
            t = join_tokens_as_a_sentence(w_df["token"].tolist())
            gs_tier.add(minTime=bos, maxTime=eos, mark=clean_textgrid_mark(t))
            # compose textgrid
            logging.info(f"composing textgrid by attaching tiers...")
            tg = TextGrid()
            for tier in (p_tier, w_tier, s_tier, gs_tier):
                tg.append(tier)
            # save texgrid to file
            fout = f"{uttid}.TextGrid"
            fout = os.path.join(os.path.realpath(args.output_dir), fout)
            logging.info(f"dumping textgrid to file {fout} ...")
            tg.write(f=fout)
        except Exception as exc:
            logging.exception("could not build TextGrid for %s; skipping utterance: %s", uttid, exc)


if __name__ == "__main__":
    args = get_args()
    logging.basicConfig(
        format="%(filename)s %(levelname)8s %(message)s", level=args.loglevel
    )
    logging.info(f"config params:")
    for arg, value in vars(args).items():
        logging.info(f"  +{arg}={value}")
    main(args)
