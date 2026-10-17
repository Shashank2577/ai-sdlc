# The question-and-answer state of one work item (#321), read from its
# comments. One definition, used by every place that needs it: the
# dispatcher's prompt step and session-end step, and answers.yml's wake.
#
# Input: the issue's comments, one array (`gh api --paginate ... | jq -s 'add // []'`).
# Output:
#   {
#     questions: {url, created_at, role, product, body} | null,  # the latest round
#     ended_at:  <created_at of the asking session's session-end comment> | null,
#     answers:   [{author, created_at, url, body}]               # replies after ended_at
#   }
#
# Agents comment with the owner's PAT, so a comment's author alone cannot
# tell an agent from a human: both read as OWNER. An answer therefore has
# to clear three bars, not one:
#   - a non-bot author with write access (OWNER / MEMBER / COLLABORATOR);
#   - no `<!-- foundry:` marker in its body, which every comment the
#     dispatcher, the wake and the question format write carries;
#   - posted after the dispatcher's session-end comment for the session
#     that asked. An agent can only comment while its session runs, so
#     nothing after that comment is the agent's.
# Once agents have their own bot identity (the GitHub App, P0-3), the
# first bar holds on its own and the other two are defence in depth.

def write_access: (.author_association // "") | IN("OWNER", "MEMBER", "COLLABORATOR");
def human: (.user.type // "") != "Bot";
def qmark: (.body // "") | capture("<!-- foundry:questions role=(?<role>[a-z][a-z-]*) product=(?<product>[A-Za-z0-9._-]+) -->");

(map(select(write_access and ((.body // "") | test("<!-- foundry:questions ")))
     | . as $c | (try qmark catch null) as $m | select($m != null)
     | {url: $c.html_url, created_at: $c.created_at, role: $m.role,
        product: $m.product, body: $c.body})
 | sort_by(.created_at) | last) as $q
| if $q == null then {questions: null, ended_at: null, answers: []}
  else
    (map(select(.created_at >= $q.created_at
                and (.user.login // "") == "github-actions[bot]"
                and ((.body // "") | test("<!-- foundry:dispatch result="))))
     | sort_by(.created_at) | first | .created_at // null) as $ended
    | {questions: $q,
       ended_at: $ended,
       answers: (if $ended == null then []
                 else map(select(.created_at > $ended and human and write_access
                                 and ((.body // "") | test("<!-- foundry:") | not)))
                      | sort_by(.created_at)
                      | map({author: .user.login, created_at, url: .html_url, body})
                 end)}
  end
