FROM debian:sid-slim AS build
RUN apt -y update && apt -y install cython3 python3-setuptools python3-setuptools-rust python3-configobj python3-dulwich python3-urllib3 python3-merge3 python3-patiencediff python3-fastbencode python3-yaml
COPY . .
RUN python3 setup.py install
FROM debian:sid
RUN apt -y update && apt -y install python3 python3-configobj python3-dulwich python3-urllib3 python3-merge3 python3-patiencediff python3-fastbencode python3-yaml
COPY --from=build /usr/local /usr/local
ENTRYPOINT ["/usr/local/bin/brz"]
