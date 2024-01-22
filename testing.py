class Log:
    _custom_loki_endpoints = {
        "loki/6": "http://loki/5:3100/loki/api/v1/push",
    }

    def disable(self, key):
        print(key)

    def enable(self):
        print(self._custom_loki_endpoints)


class Cluster:
    lokis = {
        "loki/0": "http://loki/0:3100/loki/api/v1/push",
        "loki/1": "http://loki/1:3100/loki/api/v1/push",
        "loki/2": "http://loki/2:3100/loki/api/v1/push",
        "loki/3": "http://loki/3:3100/loki/api/v1/push",
        "loki/4": "http://loki/4:3100/loki/api/v1/push",
        "loki/5": "http://loki/5:3100/loki/api/v1/push",
    }

    def get_loki_endpoints(self):
        return self.lokis


class Testaya:
    log_forwarder = Log()
    mimir_cluster = Cluster()

    def _on_loki_endpoints_received(self):
        current = self.log_forwarder._custom_loki_endpoints
        new_log_targets = self.mimir_cluster.get_loki_endpoints()

        # Identify missing keys in current that are not present in new_log_targets
        missing_keys_dict = {
            key: value for key, value in current.items() if key not in new_log_targets
        }

        # Update _custom_loki_endpoints with the new values
        current.update(new_log_targets)

        # Set _custom_loki_endpoints to the updated dictionary
        self.log_forwarder._custom_loki_endpoints = current

        # Enable log forwarder for all keys in _custom_loki_endpoints
        self.log_forwarder.enable()

        # Disable log forwarder for each missing key
        for key in missing_keys_dict:
            self.log_forwarder.disable(key)




trial = Testaya()

trial._on_loki_endpoints_received()
trial.mimir_cluster.lokis = {
    "loki/0": "http://loki/0:3500/loki/api/v1/push",
}
trial._on_loki_endpoints_received()
