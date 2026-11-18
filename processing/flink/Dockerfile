FROM flink:1.20-java17
# Kafka SQL connector (Apache 2.0) — version must match Flink minor
ARG KAFKA_CONNECTOR=3.4.0-1.20
RUN wget -q -P /opt/flink/lib \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/${KAFKA_CONNECTOR}/flink-sql-connector-kafka-${KAFKA_CONNECTOR}.jar
COPY sql /opt/omnilink/sql
