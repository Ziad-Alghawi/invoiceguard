# syntax=docker/dockerfile:1.7
# KoSIT validator (official, Java) with the XRechnung configuration, in its built-in HTTP daemon mode.
# See ADR-009. Versions and SHA-256 hashes are pinned; a mismatch fails the build.

# --- download: fetch the two release artifacts and verify them -------------------------------
FROM alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f AS download

# https://github.com/itplr-kosit/validator/releases/tag/v1.6.3
ADD --checksum=sha256:799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9 \
    https://github.com/itplr-kosit/validator/releases/download/v1.6.3/validator-1.6.3-standalone.jar \
    /opt/kosit/validator.jar

# https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/tag/v2026-08-31
ADD --checksum=sha256:2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8 \
    https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v2026-08-31/xrechnung-3.0.2-validator-configuration-2026-08-31.zip \
    /tmp/configuration.zip

RUN mkdir /opt/kosit/configuration \
    && unzip -q /tmp/configuration.zip -d /opt/kosit/configuration \
    && test -f /opt/kosit/configuration/scenarios.xml \
    && chmod -R a+rX,go-w /opt/kosit
# ADD stores remote files with mode 600; the chmod above lets the non-root runtime user read them.

# --- runtime: JRE only, non-root ---------------------------------------------------------------
FROM eclipse-temurin:21-jre-noble@sha256:0eda5830ed7b669abc246a8dc520ea8a23cab06f9a8d4b6964109e2f2394e46f

RUN useradd --system --no-create-home --shell /usr/sbin/nologin kosit
COPY --from=download --chown=root:root /opt/kosit /opt/kosit

USER kosit
EXPOSE 8080

# Health: GET /server/health. Validate: POST the invoice XML to /; 200 = accepted, 406 = rejected.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/opt/kosit/validator.jar", \
    "--scenarios", "/opt/kosit/configuration/scenarios.xml", \
    "--repository", "/opt/kosit/configuration", \
    "--daemon", "--host", "0.0.0.0", "--port", "8080"]

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=10 \
    CMD curl --fail --silent --output /dev/null http://localhost:8080/server/health || exit 1
