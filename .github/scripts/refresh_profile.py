import html
import json
import os
import re
import subprocess
import textwrap
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

OWNER = os.environ["GITHUB_REPOSITORY_OWNER"]
NOW = datetime.now(timezone.utc)
QUERY = """
query($search: String!, $openSearch: String!, $login: String!, $from: DateTime!, $to: DateTime!,
      $endCursor: String) {
  search(query: $search, type: ISSUE, first: 100, after: $endCursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        repository {
          nameWithOwner url description stargazerCount isFork
          owner { login avatarUrl(size: 48) }
          primaryLanguage { name color }
        }
      }
    }
  }
  openPRs: search(query: $openSearch, type: ISSUE, first: 1) {
    issueCount
  }
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { totalContributions }
      totalCommitContributions
      totalRepositoriesWithContributedCommits
    }
  }
}
"""


def compact(number):
    return f"{number / 1000:.1f}k" if number >= 1000 else str(number)


def badge(label, value, logo, color="8250DF", style="for-the-badge", label_color=None):
    params = {
        "label": label,
        "message": str(value),
        "color": color,
        "style": style,
        "logo": logo,
        "logoColor": "white",
    }
    if label_color:
        params["labelColor"] = label_color
    parameters = urlencode(params)
    return (
        f'<img src="https://img.shields.io/static/v1?{parameters}" '
        f'alt="{html.escape(str(value) + " " + label)}" />'
    )


def project_cell(repository):
    name = repository["nameWithOwner"]
    description = textwrap.shorten(
        repository["description"] or "", width=92, placeholder="…",
    )
    return (
        f'<img src="{repository["owner"]["avatarUrl"]}" '
        f'width="24" height="24" alt="" />&nbsp;'
        f'[`{name}`]({repository["url"]})<br>'
        f'<sub>{html.escape(description).replace("|", "&#124;")}</sub>'
    )


def replace_section(text, name, content):
    pattern = re.compile(
        rf"(<!-- AUTO:{name}:START -->).*?(<!-- AUTO:{name}:END -->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise ValueError(f"Missing marker <!-- AUTO:{name}:START/END --> in README.md")
    return pattern.sub(rf"\1\n{content}\n\2", text, count=1)


def main():
    pages = json.loads(
        subprocess.check_output(
            [
                "gh", "api", "graphql", "--paginate", "--slurp",
                "-f", f"query={QUERY}",
                "-f", f"search=author:{OWNER} is:pr is:merged is:public",
                "-f", f"openSearch=author:{OWNER} is:pr is:open -user:{OWNER} is:public",
                "-f", f"login={OWNER}",
                "-f", f"from={(NOW - timedelta(days=90)).isoformat()}",
                "-f", f"to={NOW.isoformat()}",
            ],
            encoding="utf-8",
        ),
    )
    repositories = {}
    counts = Counter()
    for page in pages:
        for pull_request in page["data"]["search"]["nodes"]:
            repository = pull_request["repository"]
            if (
                repository["owner"]["login"].lower() != OWNER.lower()
                and not repository["isFork"]
                and repository["stargazerCount"] >= 1000
            ):
                name = repository["nameWithOwner"]
                repositories[name] = repository
                counts[name] += 1

    projects = sorted(
        repositories.values(), key=lambda repo: repo["stargazerCount"], reverse=True,
    )
    open_count = pages[0]["data"]["openPRs"]["issueCount"]
    activity = pages[0]["data"]["user"]["contributionsCollection"]

    merged_search_url = (
        f"https://github.com/search?q=is%3Apr+author%3A{OWNER}+is%3Amerged+-user%3A{OWNER}+is%3Apublic&type=pullrequests"
    )
    open_search_url = (
        f"https://github.com/search?q=is%3Apr+author%3A{OWNER}+is%3Aopen+-user%3A{OWNER}+is%3Apublic&type=pullrequests"
    )

    stats_block = "\n".join([
        '<p align="center">',
        f'  <a href="{merged_search_url}">{badge("Merged PRs", sum(counts.values()), "github", color="2ea44f", label_color="25364a")}</a>',
        f'  <a href="{open_search_url}">{badge("Open PRs", open_count, "github", color="168b83", label_color="25364a")}</a>',
        "  " + badge("Upstream Repos", len(projects), "github", color="8250DF", label_color="25364a"),
        "  " + badge(
            "Upstream Stars",
            compact(sum(repo["stargazerCount"] for repo in projects)),
            "github",
            color="397ac4",
            label_color="25364a",
        ),
        "</p>",
    ])

    table_lines = [
        "| Project | ★ | Language | Merged |",
        "| :--- | ---: | :--- | ---: |",
    ]
    for repository in projects[:5]:
        language = repository["primaryLanguage"]
        language_badge = (
            badge(
                "", language["name"], language["name"].lower(),
                language["color"].removeprefix("#"), "flat-square",
            )
            if language else "—"
        )
        merged_url = repository["url"] + "/pulls?" + urlencode(
            {"q": f"is:pr is:merged author:{OWNER}"},
        )
        table_lines.append(
            f'| {project_cell(repository)} '
            f'| {compact(repository["stargazerCount"])} | {language_badge} '
            f'| [{counts[repository["nameWithOwner"]]}]({merged_url}) |',
        )
    if len(projects) > 5:
        remaining = projects[5:]
        details = "<br>".join(
            f'{project_cell(repo)} · {counts[repo["nameWithOwner"]]} merged'
            for repo in remaining
        )
        table_lines.append(
            f'| <details><summary>… and {len(remaining)} more</summary><br>'
            f'{details}</details> '
            f'| {compact(sum(repo["stargazerCount"] for repo in remaining))} '
            f'| — | {sum(counts[repo["nameWithOwner"]] for repo in remaining)} |',
        )
    table_lines.extend([
        "",
        "<sub>Public merged PRs in upstream projects with 1,000+ stars. "
        "Stars belong to the projects. Counts link to the merged PRs. "
        f'Updated daily · {NOW:%Y-%m-%d} UTC.</sub>',
    ])
    table_block = "\n".join(table_lines)

    activity_block = "\n".join([
        '<p align="center">',
        "  " + badge(
            "Contributions",
            compact(activity["contributionCalendar"]["totalContributions"]),
            "github",
        ),
        "  " + badge("Commits", compact(activity["totalCommitContributions"]), "git"),
        "  " + badge(
            "Commit repositories",
            activity["totalRepositoriesWithContributedCommits"],
            "github",
        ),
        "</p>",
    ])

    readme_path = Path("README.md")
    readme_text = readme_path.read_text(encoding="utf-8")
    readme_text = replace_section(readme_text, "STATS", stats_block)
    readme_text = replace_section(readme_text, "TABLE", table_block)
    readme_text = replace_section(readme_text, "ACTIVITY", activity_block)
    readme_path.write_text(readme_text, encoding="utf-8")
    print(f"Rendered {sum(counts.values())} merged PRs across {len(projects)} projects.")


if __name__ == "__main__":
    main()
