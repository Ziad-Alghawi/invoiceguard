# syntax=docker/dockerfile:1.7
# KoSIT validator (official, Java) with the XRechnung configuration, in its built-in HTTP daemon mode,
# and the KoSIT XRechnung visualization in the same JVM on a second port (src/, ADR-029).
# See ADR-009. Versions and SHA-256 hashes are pinned; a mismatch fails the build.

# --- download: fetch the release artifacts and verify them ------------------------------------
FROM alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f AS download

# https://github.com/itplr-kosit/validator/releases/tag/v1.6.3
ADD --checksum=sha256:799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9 \
    https://github.com/itplr-kosit/validator/releases/download/v1.6.3/validator-1.6.3-standalone.jar \
    /opt/kosit/validator.jar

# https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/tag/v2026-08-31
ADD --checksum=sha256:2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8 \
    https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v2026-08-31/xrechnung-3.0.2-validator-configuration-2026-08-31.zip \
    /tmp/configuration.zip

# https://github.com/itplr-kosit/xrechnung-visualization/releases/tag/v2026-10-13
ADD --checksum=sha256:ecf3913029218822ee4c90a86a3e23689768bf3568a061cf9bc742115e52264e \
    https://github.com/itplr-kosit/xrechnung-visualization/releases/download/v2026-10-13/xrechnung-3.0.2-visualization-2026-10-13.zip \
    /tmp/visualization.zip

# Only the stylesheets of the visualization are kept (no test instances, no PDF fonts).
RUN mkdir /opt/kosit/configuration /opt/kosit/visualization \
    && unzip -q /tmp/configuration.zip -d /opt/kosit/configuration \
    && test -f /opt/kosit/configuration/scenarios.xml \
    && unzip -q /tmp/visualization.zip 'xsl/*' -d /opt/kosit/visualization \
    && test -f /opt/kosit/visualization/xsl/xrechnung-html.xsl \
    && chmod -R a+rX,go-w /opt/kosit
# ADD stores remote files with mode 600; the chmod above lets the non-root runtime user read them.

# --- build: compile the launcher (src/) against the validator jar, which brings Saxon ----------
FROM eclipse-temurin:21-jdk-noble@sha256:dc333cdac241f073941f043792f2a2f9b790bfe7cd98ef2843c08880986708de AS build
COPY --from=download /opt/kosit/validator.jar /build/validator.jar
COPY src /build/src
RUN javac --release 21 -Xlint:all -Werror -cp /build/validator.jar -d /build/classes \
        /build/src/invoiceguard/validator/Main.java \
    && jar --create --file /build/invoiceguard-validator.jar -C /build/classes .

# --- runtime: JRE only, non-root ---------------------------------------------------------------
FROM eclipse-temurin:21-jre-noble@sha256:977602aad3cf25b74bbb4c8e7532060eef80e1f1288932da35f5fbecd6159b65

# Fixed IDs, so Kubernetes can check runAsNonRoot and the chart sets the same user (R4-3).
RUN groupadd --system --gid 999 kosit && useradd --system --uid 999 --gid kosit --no-create-home --shell /usr/sbin/nologin kosit
COPY --from=download --chown=root:root /opt/kosit /opt/kosit
COPY --from=build --chown=root:root /build/invoiceguard-validator.jar /opt/kosit/invoiceguard-validator.jar

USER 999:999
EXPOSE 8080 8082

# Health: GET /server/health. Validate: POST the invoice XML to /; 200 = accepted, 406 = rejected.
# Visualize (port 8082): POST the invoice XML to /visualize?lang=de or ?lang=en; 200 = HTML.
# The launcher starts the visualization, then hands these arguments to the official daemon.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", \
    "-cp", "/opt/kosit/validator.jar:/opt/kosit/invoiceguard-validator.jar", "invoiceguard.validator.Main", \
    "--scenarios", "/opt/kosit/configuration/scenarios.xml", \
    "--repository", "/opt/kosit/configuration", \
    "--daemon", "--host", "0.0.0.0", "--port", "8080"]

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=10 \
    CMD curl --fail --silent --output /dev/null http://localhost:8080/server/health \
        && curl --fail --silent --output /dev/null http://localhost:8082/health || exit 1
