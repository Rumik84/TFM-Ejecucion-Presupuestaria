"""Parser de CSV/TSV con detección automática de encoding y delimitador."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

import chardet
import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)

# Keywords that identify expenditure CSVs inside multi-file ZIPs (Aragón ZIPs)
_GASTO_KEYWORDS = ("gasto", "partida", "ejecucion", "presupuesto", "consol")

_NUM_TOKEN = re.compile(r"\d[\d.,]*\d")


_NUM_FIELD = re.compile(r"-?\d[\d.,]*\d")


def _collect_number_tokens(
    text_iter, delimiter: str = ",", max_tokens: int = 3000, max_bytes: int = 20_000_000
) -> list[str]:
    """Recoge valores de CAMPO numéricos CON separador ('.'/',') escaneando líneas.

    Divide cada línea por el delimitador y examina cada campo por separado (para no
    unir columnas a través del delimitador, p.ej. `2019,38006`). Salta números sin
    separador (códigos, ceros), que no informan del formato decimal — importante en
    ficheros cuya cabecera son miles de filas a 0 (p.ej. porcentajes de Canarias).
    Escanea hasta reunir `max_tokens` (o agotar `max_bytes`).
    """
    toks: list[str] = []
    read = 0
    for line in text_iter:
        read += len(line)
        for field in line.rstrip("\r\n").split(delimiter):
            field = field.strip().strip('"')
            if ("," in field or "." in field) and _NUM_FIELD.fullmatch(field):
                toks.append(field)
        if len(toks) >= max_tokens or read >= max_bytes:
            break
    return toks


def _infer_number_format(tokens) -> tuple[str, str | None] | None:
    """Deduce (decimal, thousands) a partir de los NÚMEROS (no del encoding).

    El encoding (UTF-8 vs Latin-1) NO determina si los importes usan '.' o ',' como
    decimal: hay ficheros ASCII/Latin-1 con decimal '.' (p.ej. SDMX de Canarias:
    `89932302.14`). Inferir el decimal del encoding hace que un '.' decimal se trate
    como separador de miles → importes ×100/×1000. Aquí se vota sobre los tokens:
      - '1.234.567,89' / '1234,56'  → europeo  (decimal ',', miles '.')
      - '89932302.14' / '1,234,567.89' → anglosajón (decimal '.', sin miles)
    Acepta una cadena o un iterable de tokens. Devuelve None si no hay señal.
    """
    if isinstance(tokens, str):
        tokens = _NUM_TOKEN.findall(tokens)[:5000]
    eu = anglo = 0
    for tok in tokens:
        has_c, has_d = "," in tok, "." in tok
        if has_c and has_d:
            # el ÚLTIMO separador es el decimal
            if tok.rfind(",") > tok.rfind("."):
                eu += 1
            else:
                anglo += 1
        elif has_c:
            frac = tok.rsplit(",", 1)[1]
            if tok.count(",") > 1:          # '1,234,567' -> miles anglosajón
                anglo += 1
            elif len(frac) in (1, 2):       # '1234,56' -> decimal europeo
                eu += 1
            # '1,234' (una coma, 3 dígitos) = ambiguo -> no vota
        elif has_d:
            frac = tok.rsplit(".", 1)[1]
            if tok.count(".") > 1:          # '1.234.567' -> miles europeo
                eu += 1
            elif len(frac) in (1, 2):       # '89932302.14' -> decimal anglosajón
                anglo += 1
            # '1.234' (un punto, 3 dígitos) = ambiguo -> no vota
    if anglo > eu:
        return (".", None)
    if eu > anglo:
        return (",", ".")
    return None


class CSVParser:
    """Parser de archivos CSV/TSV con detección robusta de dialecto."""

    def parse(self, path: Path) -> pd.DataFrame:
        if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
            return self._parse_zip(path)
        encoding = self._detect_encoding(path)
        delimiter = self._detect_delimiter(path, encoding)
        logger.debug("Parsing CSV %s (enc=%s, delim=%r)", path.name, encoding, delimiter)

        # Formato numérico: se infiere de los PROPIOS números (robusto). Solo si no
        # hay señal se recurre al heurístico por encoding (UTF-8→'.', resto→',').
        with path.open("r", encoding=encoding, errors="replace") as fh:
            num_tokens = _collect_number_tokens(fh, delimiter)
        fmt = _infer_number_format(num_tokens)
        if fmt is not None:
            decimal_sep, thousands_sep = fmt
        else:
            is_utf8 = encoding.lower().replace("-", "").replace("_", "") in {"utf8", "utf8sig"}
            decimal_sep = "." if is_utf8 else ","
            thousands_sep = None if is_utf8 else "."

        try:
            df = pd.read_csv(
                path,
                encoding=encoding,
                sep=delimiter,
                decimal=decimal_sep,
                thousands=thousands_sep,
                na_values=["", "NA", "N/A", "nd", "-", "s/d", "..", "*"],
                keep_default_na=True,
                on_bad_lines="skip",
                low_memory=False,
            )
        except UnicodeDecodeError:
            # Fallback
            df = pd.read_csv(path, encoding="latin-1", sep=delimiter, low_memory=False)
        return df

    # ------------------------------------------------------------------
    def _parse_zip(self, path: Path) -> pd.DataFrame:
        """Extrae y concatena los archivos relevantes de un ZIP (CSV o XLSX)."""
        with zipfile.ZipFile(path) as zf:
            all_names = zf.namelist()

        csv_names = [n for n in all_names if n.lower().endswith(".csv")]
        xlsx_names = [n for n in all_names if n.lower().endswith((".xlsx", ".xls"))]

        # Prefer CSV files; fall back to XLSX if ZIP has no CSVs
        if csv_names:
            selected = [n for n in csv_names if any(kw in n.lower() for kw in _GASTO_KEYWORDS)]
            if not selected:
                selected = csv_names
            return self._read_csv_members(path, selected)
        elif xlsx_names:
            selected = [n for n in xlsx_names if any(kw in n.lower() for kw in _GASTO_KEYWORDS)]
            if not selected:
                selected = xlsx_names
            return self._read_xlsx_members(path, selected)

        raise ValueError(f"No hay CSVs ni XLSX en ZIP: {path.name}")

    def _read_csv_members(self, path: Path, names: list[str]) -> pd.DataFrame:
        frames = []
        with zipfile.ZipFile(path) as zf:
            for name in names:
                raw = zf.read(name)
                detected = chardet.detect(raw[:65536])
                enc = detected.get("encoding") or "utf-8"
                confidence = detected.get("confidence") or 0
                if enc.lower() in {"ascii", "iso-8859-1", "windows-1252", "mac_turkish", "mac-turkish"} \
                        or confidence < 0.5:
                    enc = "latin-1"
                is_utf8 = enc.lower().replace("-", "").replace("_", "") in {"utf8", "utf8sig"}
                text = raw.decode(enc, errors="replace")
                delim = self._detect_delimiter_text(text)
                fmt = _infer_number_format(_collect_number_tokens(io.StringIO(text), delim))
                if fmt is not None:
                    dec_sep, thou_sep = fmt
                else:
                    dec_sep = "." if is_utf8 else ","
                    thou_sep = None if is_utf8 else "."
                try:
                    df = pd.read_csv(
                        io.StringIO(text),
                        sep=delim,
                        decimal=dec_sep,
                        thousands=thou_sep,
                        na_values=["", "NA", "N/A", "nd", "-", "s/d", "..", "*"],
                        keep_default_na=True,
                        on_bad_lines="skip",
                        low_memory=False,
                    )
                    df["_zip_source"] = name
                    frames.append(df)
                except Exception as exc:
                    logger.warning("Error leyendo %s de ZIP %s: %s", name, path.name, exc)
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True)
        logger.debug("ZIP %s: %d filas de %d CSVs", path.name, len(result), len(frames))
        return result

    def _read_xlsx_members(self, path: Path, names: list[str]) -> pd.DataFrame:
        frames = []
        with zipfile.ZipFile(path) as zf:
            for name in names:
                raw = zf.read(name)
                try:
                    sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=0)
                    for sheet_name, df in sheets.items():
                        if not df.empty:
                            df["__sheet__"] = sheet_name
                            df["_zip_source"] = name
                            frames.append(df)
                except Exception as exc:
                    logger.warning("Error leyendo XLSX %s de ZIP %s: %s", name, path.name, exc)
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True)
        logger.debug("ZIP %s: %d filas de %d XLSX sheets", path.name, len(result), len(frames))
        return result

    # ------------------------------------------------------------------
    def _detect_encoding(self, path: Path, sample_size: int = 65536) -> str:
        with path.open("rb") as f:
            sample = f.read(sample_size)
        result = chardet.detect(sample)
        enc = result.get("encoding") or "utf-8"
        confidence = result.get("confidence") or 0
        # Treat low-confidence detections and known Latin variants as latin-1.
        # mac_turkish maps 0xED→ı (dotless-i) instead of í, breaking Spanish/Galician headers.
        if enc.lower() in {"ascii", "iso-8859-1", "windows-1252", "mac_turkish", "mac-turkish"} \
                or confidence < 0.5:
            enc = "latin-1"
        return enc

    def _detect_delimiter(self, path: Path, encoding: str) -> str:
        with path.open("r", encoding=encoding, errors="replace") as f:
            return self._detect_delimiter_text(f.read(8192))

    def _detect_delimiter_text(self, sample: str) -> str:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            return dialect.delimiter
        except csv.Error:
            if sample.count(";") > sample.count(","):
                return ";"
            if sample.count("\t") > sample.count(","):
                return "\t"
            return ","
