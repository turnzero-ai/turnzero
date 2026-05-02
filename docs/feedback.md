# TurnZero Feedback

## For users

Submit UX and product feedback with:

```bash
turnzero feedback
```

This opens the hosted TurnZero feedback form configured by the maintainer. The
form provider and settings determine whether responses are public or private.

Useful feedback includes:

- OS
- TurnZero version
- Install method
- AI client
- Embedding backend
- What you tried
- What happened
- What you expected
- Friction rating
- Whether TurnZero reduced repeated AI corrections

Do not include:

- API keys
- secrets
- raw prompts
- transcripts
- private repo names
- customer data
- confidential priors

Feedback submitted through the hosted form is separate from anonymous telemetry.
Local correction feedback captured with
`turnzero feedback --prompt ... --correction ...` stays on your machine unless
you manually share it.

## For maintainers

Create one hosted form using Tally, Google Forms, Typeform, Formspree, or a
similar free hosted-form option. Use
[docs/feedback-form-template.md](feedback-form-template.md) as the question
template.

Configure the form URL in either of these ways:

- Set `TURNZERO_FEEDBACK_URL` in the user's environment.
- Replace the repository placeholder
  `https://tally.so/r/REPLACE_WITH_TURNZERO_FORM_ID`.

Users run `turnzero feedback` to open the configured form. Read responses in
the hosted-form dashboard or linked spreadsheet.

Review feedback weekly and group it by:

- install/setup
- AI client integration
- MCP behavior
- injection quality
- Personal Priors
- Expert Priors
- candidate submission/review
- harvest command
- docs/onboarding
- privacy/telemetry
- missing domain coverage

Convert actionable feedback into GitHub issues or roadmap items. Extract
candidate Expert Priors only from sanitized examples, and do not copy secrets,
raw prompts, transcripts, private repo names, customer data, or confidential
priors into issues or priors.
