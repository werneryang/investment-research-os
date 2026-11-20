"""Public, noindex readable reports. Never import private result documents.

Checks apply to the entire copied text, including metadata, comments and code.
They are a publication gate, not proof that prose is accurate or a copyright licence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import html
import os
import posixpath
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
import yaml

SCHEMA = 'research-notes.v1'
PUBLIC_REPO = 'https://github.com/werneryang/investment-research-os'
REPORT_ID = re.compile(r'(?P<company>[A-Z][A-Z0-9.-]{0,11})-(?P<date>\d{8})-(?P<slug>[a-z0-9][a-z0-9-]*)\Z')
PRIVATE_REPOS = ('company-dossiers', 'research-method-extraction')
# Site-relative link from one report page (notes/companies/<C>/<day>/<id>/) to another published report.
NOTE_LINK = re.compile(r'\.\./\.\./\.\./(?P<company>[A-Z][A-Z0-9.-]{0,11})/(?P<day>\d{4}-\d{2}-\d{2})/(?P<id>[A-Z][A-Z0-9.-]{0,11}-\d{8}-[a-z0-9][a-z0-9-]*)/(?:#[A-Za-z0-9_-]*)?\Z')
NOTE_LINK_INLINE = r'\.\./\.\./\.\./[A-Z][A-Z0-9.-]{0,11}/\d{4}-\d{2}-\d{2}/[A-Z][A-Z0-9.-]{0,11}-\d{8}-[a-z0-9][a-z0-9-]*/(?:#[A-Za-z0-9_-]*)?'
MAX_BYTES = 200_000
# Deliberately conservative automatic-publication threshold; no bypass flag.
QUOTE_WORDS, QUOTE_CJK = 25, 100


@dataclass(frozen=True)
class Issue:
    code: str
    line: int = 0


class NoteRejected(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__('报告未导入：' + ', '.join(f'{i.code} (line {i.line})' for i in issues))


def canonical(text: str) -> str:
    for _ in range(16):
        new = html.unescape(unquote(text))
        if new == text:
            break
        text = new
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c) != 'Cf')


def parser() -> MarkdownIt:
    # js-default disables raw HTML; tables are enabled. Images never cause external requests.
    return MarkdownIt('js-default', {'html': False, 'linkify': False})


def companies(root: Path) -> dict:
    p = Path(root) / 'config/notes.yaml'
    doc = yaml.safe_load(p.read_text()) if p.exists() else {}
    if doc.get('schema_version') not in (None, SCHEMA):
        raise ValueError('未知研究报告登记版本')
    return doc.get('companies', {})


def _walk(tokens):
    for t in tokens:
        yield t
        yield from _walk(t.children or [])


def _long_quote(text: str) -> bool:
    return len(re.findall(r'[A-Za-z]+(?:[’\'-][A-Za-z]+)*', text)) > QUOTE_WORDS or len(re.findall(r'[\u3400-\u9fff]', text)) > QUOTE_CJK


def boundary_issues(text: str) -> list[Issue]:
    """Never include matching secret bytes in diagnostics."""
    issues = []
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text):
        issues.append(Issue('control_character'))
    if not text:
        return issues
    if unquote(canonical(text)) != canonical(text):
        issues.append(Issue('encoding_depth_review'))
    for number, raw in enumerate(text.splitlines(), 1):
        line = canonical(raw)
        checks = {
            'local_path': r'(?i)(?:/(?:Users|home|root|Applications|Library|System|private|tmp|Volumes|etc|var|opt|usr|bin|sbin|dev|proc|sys|mnt|media|run|srv|workspace)/|~/|file:|\b[A-Z]:[/\\]|\\\\[\w.-]+\\)',
            'email': r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?i:mailto:)',
            'secret': r'(?i)(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{15,}|github_pat_[A-Za-z0-9_]{15,}|AKIA[A-Z0-9]{16}|BEGIN (?:RSA |OPENSSH )?PRIVATE KEY|Bearer\s+[A-Za-z0-9._-]{12,}|(?:api[_-]?key|access[_-]?token|secret|password|passwd|token|密[钥鑰]|令牌)\s*[:=]\s*[\"\']?[A-Za-z0-9_./+-]{8,})',
            'user_private': r'(?:你|我)\s*的\s*判\s*[断斷]|[个個]\s*人\s*判\s*[断斷]|持\s*[仓倉]|第\s*(?:10|十)\s*[节節章]|(?i:\b(?:my|your)\s+(?:holdings|portfolio|thesis)\b)|^\s*#{1,6}\s*(?:10|十)[.、\s]',
            'private_link': r'(?i)(?:https?://|git@)[^\s<>`]*(?:company-dossiers|research-method-extraction)|(?:\.\./|companies/)[^\s<>`]*results/|\]\([^)\s]*(?:company-dossiers|research-method-extraction)',
        }
        for code, pattern in checks.items():
            if re.search(pattern, line):
                issues.append(Issue(code, number))
    if len(text.encode()) > MAX_BYTES:
        issues.append(Issue('report_too_large'))
    try:
        md = parser()
        env = {}
        tokens = md.parse(text, env)
        # Raw HTML is not a supported report input (including hidden comments).
        if any(t.type in ('html_inline', 'html_block') for t in _walk(MarkdownIt('js-default', {'html': True}).parse(text))):
            issues.append(Issue('raw_html'))
        # Markdown emphasis/link labels can hide private markers from a raw scan.
        visible = []
        for t in tokens:
            if t.type == 'inline':
                visible.append(''.join(x.content if x.type in ('text', 'code_inline') else '\n' if x.type in ('softbreak', 'hardbreak') else '' for x in _walk(t.children or [])))
        visible_text = canonical('\n'.join(visible))
        whole = canonical(text)
        for code in ('email', 'secret', 'user_private', 'private_link'):
            if any(re.search(checks[code], candidate) for candidate in (whole, visible_text, re.sub(r'[*_`~]', '', whole))):
                issues.append(Issue(code))
        for i, t in enumerate(tokens):
            if t.type == 'heading_open' and i + 1 < len(tokens):
                rendered = ''.join(x.content for x in _walk(tokens[i+1].children or []) if x.type in ('text','code_inline'))
                if re.match(r'\s*(?:10|十)[.、\s]', rendered):
                    issues.append(Issue('user_private', (t.map or [0])[0]+1))
        # An arbitrary absolute filesystem path is not a permitted repository-relative citation.
        no_urls = re.sub(r'https?://[^\s<>`]+', '', whole, flags=re.I)
        no_urls = re.sub(rf'\]\({NOTE_LINK_INLINE}\)', '](', no_urls)
        if re.search(r'(?<![\w/])/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+', no_urls):
            issues.append(Issue('local_path'))
        for url in re.findall(r'https?://[^\s`<>\)]+', whole, re.I):
            parsed = urlsplit(url.rstrip('.,，。；'))
            if parsed.username or parsed.password:
                issues.append(Issue('unsafe_or_unresolved_link'))
            host = (parsed.hostname or '').lower()
            if host in ('github.com', 'raw.githubusercontent.com'):
                key = posixpath.normpath(parsed.path).strip('/').split('/')[:2]
                if [x.lower() for x in key] != ['werneryang', 'investment-research-os']:
                    issues.append(Issue('unverified_repository'))
            elif host in ('gist.github.com', 'gitlab.com', 'bitbucket.org') or host.endswith('.githubusercontent.com'):
                issues.append(Issue('unverified_repository'))
        quoted = []
        for t in tokens:
            if t.type == 'blockquote_open' and t.map:
                quoted.append('\n'.join(text.splitlines()[t.map[0]:t.map[1]]))
            if t.type in ('fence', 'code_block') and _long_quote(t.content):
                issues.append(Issue('long_quote_review', (t.map or [0])[0] + 1))
        # Sum blocks as well as checking each: splitting an excerpt is not an approval bypass.
        plain = '\n'.join(visible)
        quoted += re.findall(r'“([^”]+)”|‘([^’]+)’|「([^」]+)」|『([^』]+)』|"([^"\n]+)"|(?<!\w)\'([^\'\n]+)\'(?!\w)', plain)
        code_quotes = [t.content for t in _walk(tokens) if t.type == 'code_inline' and re.search(r'\s', t.content)]
        quoted += code_quotes
        quote_text = ' '.join(''.join(q) if isinstance(q, tuple) else q for q in quoted)
        if _long_quote(quote_text):
            issues.append(Issue('long_quote_review'))
        for t in _walk(tokens):
            if t.type == 'image':
                issues.append(Issue('image_not_allowed'))
            if t.type == 'link_open':
                url = canonical(t.attrGet('href') or '')
                parts = urlsplit(url)
                if any(p in url.lower() for p in PRIVATE_REPOS):
                    issues.append(Issue('private_link'))
                elif NOTE_LINK.fullmatch(url):
                    pass  # internal link to another report page; load_notes checks the target is published
                elif parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
                    issues.append(Issue('unsafe_or_unresolved_link'))
                elif any(p in parts.path.lower() for p in PRIVATE_REPOS):
                    issues.append(Issue('private_link'))
    except (ValueError, RecursionError):
        issues.append(Issue('invalid_markdown'))
    return list(dict.fromkeys(issues))


def _public_target(root: Path, rel: str) -> str:
    rel = unquote(rel)
    file = root / rel
    if not (rel.startswith(('methodology/records/', 'docs/', 'config/studies/')) and '..' not in Path(rel).parts
            and file.is_file() and file.resolve().is_relative_to(root.resolve())):
        raise NoteRejected([Issue('unverified_public_target')])
    try:
        # Pin only bytes already on the public tracking branch, never a private/local file.
        commit = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        blob = subprocess.check_output(['git', 'show', f'{commit}:{rel}'], cwd=root, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise NoteRejected([Issue('unverified_public_target')]) from None
    if blob != file.read_bytes():
        raise NoteRejected([Issue('unverified_public_target')])
    return f'{PUBLIC_REPO}/blob/{commit}/{quote(rel, safe="/")}'


def _published_note(root: Path, identifier: str) -> str | None:
    """Site-relative link to an already published report copy, or None."""
    try:
        company, day = _parts(identifier)
    except NoteRejected:
        return None
    f = root / 'notes/companies' / company / day / (identifier + '.md')
    if f.is_file() and not f.is_symlink() and f.resolve().is_relative_to((root / 'notes/companies').resolve()):
        return f'../../../{company}/{day}/{identifier}/'
    return None


def _dossier_target(root: Path, company: str | None, target: str):
    """Classify a relative link written in companies/<C>/reports/<id>.md of company-dossiers.

    Returns ('note', href) for a published report, ('private', id-or-None) for an unpublished
    report, a result file or any other dossiers file, ('record', rel) for a research-os record,
    or None when the target is not a relative dossiers path (left for the boundary check).
    """
    target = unquote(target.split('#', 1)[0])
    if not target or urlsplit(target).scheme:
        return None  # URLs (including ones into a private repo) are left for the boundary check
    if target.startswith(('/', '~')):
        m = re.search(r'company-dossiers/(companies/.+)', target)
        if not m:
            return None
        resolved = m.group(1)
    else:
        m = re.fullmatch(r'(?:(?:\.\./)*investment-research-os/)?(methodology/records/[A-Za-z0-9_.-]+\.ya?ml)', target)
        if m:
            return ('record', m.group(1))
        # The source company only matters for same-company links; their ids carry the company anyway.
        resolved = posixpath.normpath(posixpath.join('companies', company or 'SELF', 'reports', target))
    if not resolved.startswith('companies/'):
        return None
    m = re.fullmatch(r'companies/[A-Z0-9.-]+/(reports|results)/([^/]+)\.md', resolved)
    if m and REPORT_ID.fullmatch(m.group(2)):
        if m.group(1) == 'reports':
            href = _published_note(root, m.group(2))
            if href:
                return ('note', href)
        return ('private', m.group(2))
    return ('private', None)


def clean_report(root: Path, text: str, company: str | None = None) -> tuple[str, int]:
    """Only deterministic path/link cleanup; no silent deletion of user-private prose.

    Links between reports (builds_on / see_also) point to the published page when the other
    report is on the site; otherwise, and for results or other private files, only plain text stays.
    """
    count = 0
    def unpublished(label: str, ident: str | None) -> str:
        label = label.strip()
        if ident is None:
            return f'{label}（未公开）' if label else '（未公开）'
        if not label or label.strip('`') in (ident, ident + '.md') or '/' in label:
            return f'（见 {ident}，未公开）'
        return f'{label}（见 {ident}，未公开）'
    def link(m):
        nonlocal count
        label, target = m.group(1), m.group(2)
        kind = _dossier_target(root, company, target)
        if kind is None:
            return m.group(0)
        count += 1
        if kind[0] == 'note':
            return f'[{label}]({kind[1]})'
        if kind[0] == 'record':
            return f'[{label}]({_public_target(root, kind[1])})'
        return unpublished(label, kind[1])
    text = re.sub(r'(?<!!)\[([^\]\n]*)\]\(([^)\s]+)\)', link, text)
    # Bare (unlinked) private result or report paths become a plain identifier.
    ident = r'[A-Z][A-Z0-9.-]*-\d{8}-[a-z0-9-]+'
    private_target = rf'(?:[^\s)<>`]*company-dossiers/companies/[A-Z0-9.-]+/(?:results|reports)/|(?<![\w/.])(?:\.\./)?(?:\.\./[A-Z0-9.-]+/)?(?:results|reports)/)({ident})\.md'
    def plain_path(m):
        nonlocal count
        count += 1
        return m.group(1)
    text = re.sub(private_target, plain_path, text)
    # Known public repository paths only; arbitrary local paths remain and fail validation.
    pattern = r'/(?:Users|home)/[^\s`<>\[\]()]*?/investment-research-os/([A-Za-z0-9_./-]+\.(?:yaml|md))'
    def public(m):
        nonlocal count
        count += 1
        return _public_target(root, m.group(1))
    text = re.sub(pattern, public, text)
    # Repository-relative record references can also be made directly clickable.
    text = re.sub(r'(?<![\w/])methodology/records/[A-Za-z0-9_.-]+\.ya?ml',
                  lambda m: _public_target(root, m.group(0)), text)
    text = re.sub(r'`(https://github\.com/werneryang/investment-research-os/blob/[^`\s]+)`', r'[公开记录](\1)', text)
    return text, count


def _parts(identifier: str) -> tuple[str, str]:
    m = REPORT_ID.fullmatch(identifier)
    if not m:
        raise NoteRejected([Issue('invalid_report_id')])
    d = m['date']
    try:
        day = date.fromisoformat(f'{d[:4]}-{d[4:6]}-{d[6:]}').isoformat()
    except ValueError:
        raise NoteRejected([Issue('invalid_report_date')]) from None
    return m['company'], day


def import_report(root: Path, source: Path) -> dict:
    root, source = Path(root).resolve(), Path(source).absolute()
    if source.is_symlink() or not source.is_file() or source != source.resolve():
        raise NoteRejected([Issue('source_symlink_or_missing')])
    if source.suffix != '.md' or source.parent.name != 'reports' or source.parent.parent.parent.name != 'companies':
        raise NoteRejected([Issue('reports_only')])
    company, day = _parts(source.stem)
    if source.parent.parent.name != company or company not in companies(root):
        raise NoteRejected([Issue('unknown_or_mismatched_company')])
    with source.open('rb') as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise NoteRejected([Issue('report_too_large')])
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise NoteRejected([Issue('not_utf8')]) from None
    if text.startswith('---'):
        raise NoteRejected([Issue('source_frontmatter_not_allowed')])
    cleaned, rewrites = clean_report(root, text, company)
    issues = boundary_issues(cleaned)
    if issues:
        raise NoteRejected(issues)
    heading = re.search(r'^#\s+(.+)$', cleaned, re.M)
    if not heading or not heading.group(1).strip() or len(heading.group(1)) > 300:
        raise NoteRejected([Issue('invalid_title')])
    cfg = companies(root)[company]
    meta = {'schema_version': SCHEMA, 'id': source.stem, 'company': company, 'company_name': cfg['name'],
            'cik': cfg['cik'], 'date': day, 'title': heading.group(1), 'source_report_id': source.stem,
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'rewrites': rewrites, 'language': 'zh', 'robots': 'noindex'}
    copied = '---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + '---\n\n' + cleaned
    if boundary_issues(copied):
        raise NoteRejected(boundary_issues(copied))
    dest = root / 'notes/companies' / company / day / (source.stem + '.md')
    for parent in [dest, *dest.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise NoteRejected([Issue('destination_symlink')])
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.import-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(copied)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {'id': source.stem, 'path': dest.relative_to(root).as_posix(), 'rewrites': rewrites,
            'sha256': hashlib.sha256(copied.encode()).hexdigest(), 'public_boundary': 'pass'}


def load_notes(root: Path) -> tuple[list[dict], list[dict]]:
    """Validate again at build: one rejected note never publishes or blocks unrelated studies."""
    good, rejected = [], []
    base = Path(root) / 'notes/companies'
    if base.exists() and (base.is_symlink() or base.parent.is_symlink() or not base.resolve().is_relative_to(Path(root).resolve())):
        return [], [{'path': 'notes/companies', 'issues': ['note_symlink']}]
    for path in sorted(base.rglob('*.md')) if base.exists() else []:
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
                raise NoteRejected([Issue('note_symlink')])
            text = path.read_text()
            if not text.startswith('---\n'):
                raise NoteRejected([Issue('missing_metadata')])
            front, separator, body = text[4:].partition('\n---\n')
            if not separator:
                raise NoteRejected([Issue('missing_metadata_delimiter')])
            if len(text.encode()) > MAX_BYTES:
                raise NoteRejected([Issue('report_too_large')])
            meta = yaml.safe_load(front)
            if not isinstance(meta, dict):
                raise NoteRejected([Issue('invalid_metadata')])
            company, day = _parts(path.stem)
            cfg = companies(root).get(company)
            if not (cfg and meta.get('schema_version') == SCHEMA and meta.get('id') == path.stem
                    and meta.get('company') == company and str(meta.get('date')) == day
                    and meta.get('cik') == cfg['cik'] and meta.get('company_name') == cfg['name']
                    and meta.get('language') == 'zh' and meta.get('robots') == 'noindex'
                    and path.parent.name == day and path.parent.parent.name == company):
                raise NoteRejected([Issue('invalid_metadata')])
            heading = re.search(r'^#\s+(.+)$', body, re.M)
            if not (isinstance(meta.get('title'), str) and len(meta['title']) <= 300 and heading and meta['title'] == heading.group(1)
                    and isinstance(meta.get('rewrites'), int) and not isinstance(meta['rewrites'], bool) and meta['rewrites'] >= 0):
                raise NoteRejected([Issue('invalid_metadata')])
            issues = boundary_issues(text) + boundary_issues(yaml.safe_dump(meta, allow_unicode=True))
            allowed = {'schema_version', 'id', 'company', 'company_name', 'cik', 'date', 'title', 'source_report_id', 'source_sha256', 'rewrites', 'language', 'robots'}
            if set(meta) != allowed or meta.get('source_report_id') != path.stem or not re.fullmatch(r'[a-f0-9]{64}', str(meta.get('source_sha256', ''))):
                issues.append(Issue('invalid_metadata'))
            if issues:
                raise NoteRejected(issues)
            good.append({**meta, 'body': body.lstrip(), 'path': path.relative_to(root).as_posix(),
                         'href': f'notes/companies/{company}/{day}/{path.stem}/'})
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError, RecursionError) as exc:
            codes = [i.code for i in exc.issues] if isinstance(exc, NoteRejected) else ['invalid_note']
            label = path.relative_to(root).as_posix()
            if boundary_issues(label):
                label = 'notes/rejected-' + hashlib.sha256(label.encode()).hexdigest()[:12]
            rejected.append({'path': label, 'issues': sorted(set(codes))})
    # A link to another report must land on a report page that is itself published in this build.
    while True:
        hrefs = {n['href'] for n in good}
        broken = [n for n in good if any(f"notes/companies/{m['company']}/{m['day']}/{m['id']}/" not in hrefs
                                         for m in (NOTE_LINK.fullmatch(h) for h in re.findall(r'\]\(([^)\s]+)\)', n['body'])) if m)]
        if not broken:
            return good, rejected
        for n in broken:
            good.remove(n)
            rejected.append({'path': n['path'], 'issues': ['unresolved_note_link']})


SITE_LOCAL_PATH = re.compile(r'(?i)file:|~/|/(?:Users|home)/|\b[A-Z]:\\\\')
SITE_ATTR = re.compile(r'''(?i)\b(?:href|src|action)\s*=\s*(?:"([^"]*)"|'([^']*)')''')


def site_boundary_issues(out: Path) -> list[dict]:
    """Grep the built site: no page may link to a private repository or a local path.

    Report pages (notes/) are also checked in their visible text. Diagnostics give the page and
    the category only.
    """
    out = Path(out)
    found = []
    for page in sorted(out.rglob('*.html')):
        rel = page.relative_to(out).as_posix()
        text = page.read_text(encoding='utf-8', errors='replace')
        codes = set()
        for m in SITE_ATTR.finditer(text):
            value = canonical(m.group(1) or m.group(2) or '')
            if any(p in value.lower() for p in PRIVATE_REPOS):
                codes.add('private_link')
            if SITE_LOCAL_PATH.search(value):
                codes.add('local_path')
        if rel.startswith('notes/'):
            plain = canonical(text)
            if any(p in plain.lower() for p in PRIVATE_REPOS):
                codes.add('private_link')
            if SITE_LOCAL_PATH.search(plain):
                codes.add('local_path')
        found += [{'path': rel, 'issue': c} for c in sorted(codes)]
    return found
