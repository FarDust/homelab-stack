# `docker stack config` prints resolved secrets

`docker stack config -c <file>` renders the whole stack with environment substitution applied. Every API key and password passed through `${VAR}` interpolation or `environment:` appears in clear text, for every service in the file, not only the one you care about.

## Symptom

A key shows up in a terminal, an agent transcript or a log after someone ran the command to check one service's settings.

## Safe alternatives

- Read one non-secret field: `docker service inspect <service> --format '{{json .Spec.TaskTemplate.ContainerSpec.Image}}'`.
- Compare configs by version or hash instead of by content.
- When the render is needed, pipe it through a masking filter and keep the raw output out of the terminal and out of any captured session.
- Prefer secrets mounted as files (`secrets:`) over environment values, so the rendered stack holds a reference rather than the value.

## If it already happened

Follow [scrubbing a leaked secret from transcripts](scrubbing-a-leaked-secret-from-transcripts.md).

Entities: [[Docker Swarm]]
