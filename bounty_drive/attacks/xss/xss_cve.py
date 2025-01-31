import hashlib
import json
import random
import re
import sys
from termcolor import cprint

from utils.app_config import USER_AGENTS
from requester.request_manager import (
    de_json,
    handle_anchor,
    js_extractor,
    start_request,
)


checkedScripts = set()


def is_defined(o):
    return o is not None


def scan(data, extractor, definitions, matcher=None):
    """Scan the given data for potential vulnerabilities using the specified extractor and definitions.

    Args:
        data (Any): The data to be scanned.
        extractor (Any): The extractor to be used for scanning.
        definitions (dict): The definitions of vulnerabilities.
        matcher (callable, optional): The matching function to be used for matching vulnerabilities. Defaults to None.

    Returns:
        list: A list of detected vulnerabilities, each represented as a dictionary with keys 'version', 'component', and 'detection'.
    """
    matcher = matcher or _simple_match
    detected = []
    for component in definitions:
        extractors = definitions[component].get("extractors", None).get(extractor, None)
        if not is_defined(extractors):
            continue
        for i in extractors:
            match = matcher(i, data)
            if match:
                detected.append(
                    {"version": match, "component": component, "detection": extractor}
                )
    return detected


def _simple_match(regex, data):
    regex = de_json(regex)
    match = re.search(regex, data)
    return match.group(1) if match else None


def _replacement_match(regex, data):
    """Match and replace a regular expression pattern in the given data.

    Args:
        regex (str): The regular expression pattern to match and replace.
        data (str): The data to search for the regular expression pattern.

    Returns:
        str: The replaced string if a match is found, otherwise None.
    """
    try:
        regex = de_json(regex)
        group_parts_of_regex = r"^\/(.*[^\\])\/([^\/]+)\/$"
        ar = re.search(group_parts_of_regex, regex)
        search_for_regex = "(" + ar.group(1) + ")"
        match = re.search(search_for_regex, data)
        ver = None
        if match:
            ver = re.sub(ar.group(1), ar.group(2), match.group(0))
            return ver

        return None
    except:
        return None


def _scanhash(hash, definitions):
    for component in definitions:
        hashes = definitions[component].get("extractors", None).get("hashes", None)
        if not is_defined(hashes):
            continue
        for i in hashes:
            if i == hash:
                return [
                    {"version": hashes[i], "component": component, "detection": "hash"}
                ]

    return []


def check(results, definitions):
    """Check for vulnerabilities in the given results.

    This function iterates over the results and checks if each result has any vulnerabilities
    based on the definitions provided.

    Args:
        results (list): A list of results to check for vulnerabilities.
        definitions (dict): A dictionary containing definitions of vulnerabilities.

    Returns:
        list: A list of results with vulnerabilities appended to each result.

    """
    for r in results:
        result = r

        if not is_defined(definitions[result.get("component", None)]):
            continue
        vulns = definitions[result.get("component", None)].get("vulnerabilities", None)
        for i in range(len(vulns)):
            if not _is_at_or_above(
                result.get("version", None), vulns[i].get("below", None)
            ):
                if is_defined(vulns[i].get("atOrAbove", None)) and not _is_at_or_above(
                    result.get("version", None), vulns[i].get("atOrAbove", None)
                ):
                    continue

                vulnerability = {"info": vulns[i].get("info", None)}
                if vulns[i].get("severity", None):
                    vulnerability["severity"] = vulns[i].get("severity", None)

                if vulns[i].get("identifiers", None):
                    vulnerability["identifiers"] = vulns[i].get("identifiers", None)

                result["vulnerabilities"] = result.get("vulnerabilities", None) or []
                result["vulnerabilities"].append(vulnerability)

    return results


def unique(ar):
    return list(set(ar))


def _is_at_or_above(version1, version2):
    # print "[",version1,",", version2,"]"
    v1 = re.split(r"[.-]", version1)
    v2 = re.split(r"[.-]", version2)

    l = len(v1) if len(v1) > len(v2) else len(v2)
    for i in range(l):
        v1_c = _to_comparable(v1[i] if len(v1) > i else None)
        v2_c = _to_comparable(v2[i] if len(v2) > i else None)
        # print v1_c, "vs", v2_c
        if not isinstance(v1_c, type(v2_c)):
            return isinstance(v1_c, int)
        if v1_c > v2_c:
            return True
        if v1_c < v2_c:
            return False

    return True


def _to_comparable(n):
    if not is_defined(n):
        return 0
    if re.search(r"^[0-9]+$", n):
        return int(str(n), 10)

    return n


def _replace_version(jsRepoJsonAsText):
    return re.sub(r"[.0-9]*", "[0-9][0-9.a-z_\-]+", jsRepoJsonAsText)


def is_vulnerable(results):
    for r in results:
        if "vulnerabilities" in r:
            # print r
            return True

    return False


def scan_uri(uri, definitions):
    result = scan(uri, "uri", definitions)
    return check(result, definitions)


def scan_filename(fileName, definitions):
    result = scan(fileName, "filename", definitions)
    return check(result, definitions)


def scan_file_content(content, definitions):
    result = scan(content, "filecontent", definitions)
    if len(result) == 0:
        result = scan(content, "filecontentreplace", definitions, _replacement_match)

    if len(result) == 0:
        result = _scanhash(
            hashlib.sha1(content.encode("utf8")).hexdigest(), definitions
        )

    return check(result, definitions)


def main_scanner(uri, response):
    """Scan the given URI and file content for XSS vulnerabilities.

    This function takes a URI and its corresponding response content as input,
    and scans them for XSS vulnerabilities using the definitions provided in
    the 'attacks/xss/definitions.json' file.

    Args:
        uri (str): The URI to be scanned for XSS vulnerabilities.
        response (str): The response content associated with the URI.

    Returns:
        dict: A dictionary containing the scan result. The dictionary has the
        following keys:
            - 'component': The component associated with the first detected
              vulnerability.
            - 'version': The version associated with the first detected
              vulnerability.
            - 'vulnerabilities': A list of dictionaries, where each dictionary
              represents a detected vulnerability. Each vulnerability dictionary
              contains information about the vulnerability, such as its type,
              description, and impact.
    """
    definitions = json.loads("attacks/xss/definitions.json")
    uri_scan_result = scan_uri(uri, definitions)
    filecontent = response
    filecontent_scan_result = scan_file_content(filecontent, definitions)
    uri_scan_result.extend(filecontent_scan_result)
    result = {}
    if uri_scan_result:
        result["component"] = uri_scan_result[0]["component"]
        result["version"] = uri_scan_result[0]["version"]
        result["vulnerabilities"] = []
        vulnerabilities = set()
        for i in uri_scan_result:
            k = set()
            try:
                for j in i["vulnerabilities"]:
                    vulnerabilities.add(str(j))
            except KeyError:
                pass
        for vulnerability in vulnerabilities:
            result["vulnerabilities"].append(
                json.loads(vulnerability.replace("'", '"'))
            )
        return result


def retire_js(url, response, config, proxies):
    """Retires JavaScript code from the given URL and performs vulnerability scanning.

    Args:
        url (str): The URL to retire JavaScript code from.
        response (str): The response received from the URL.
        config (dict): Configuration settings for the scanning process.
        proxies (dict): Proxy settings for the request.

    Returns:
        None
    """
    scripts = js_extractor(response)
    cprint(
        "Extracted %i scripts from %s" % (len(scripts), url),
        color="green",
        file=sys.stderr,
    )
    for script in scripts:
        if script not in checkedScripts:
            checkedScripts.add(script)
            uri = handle_anchor(url, script)

            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "X-HackerOne-Research": "elniak",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip,deflate",
                "Connection": "close",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
                "cache-control": "max-age=0",
            }
            cprint(
                f"Searching for GET Script - Session (n° 0): {uri} \n\t - parameters NONE \n\t - headers {headers} \n\t - xss - with proxy {proxies} ...",
                "yellow",
                file=sys.stderr,
            )
            response = start_request(
                base_url=uri,
                params="",
                GET=True,
                proxies=proxies,
                secured=True
                if proxies and "https" in proxies and "socks" in proxies["https"]
                else False,
                config=config,
                headers=headers,
            )

            if hasattr(response, "text"):
                response = response.text
            else:
                response = ""

            result = main_scanner(uri, response)

            if result:
                cprint(
                    "Vulnerable component: "
                    + result["component"]
                    + " v"
                    + result["version"],
                    color="green",
                    file=sys.stderr,
                )
                cprint("Component location: %s" % uri, color="green", file=sys.stderr)

                details = result["vulnerabilities"]
                cprint(
                    "Total vulnerabilities: %i" % len(details),
                    color="green",
                    file=sys.stderr,
                )
                for detail in details:
                    cprint(
                        "%sSummary: %s" % (detail["identifiers"]["summary"]),
                        color="green",
                        file=sys.stderr,
                    )
                    cprint(
                        "Severity: %s" % detail["severity"],
                        color="green",
                        file=sys.stderr,
                    )
                    cprint(
                        "CVE: %s" % detail["identifiers"]["CVE"][0],
                        color="green",
                        file=sys.stderr,
                    )
