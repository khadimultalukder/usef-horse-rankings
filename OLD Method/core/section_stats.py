from collections import defaultdict


class SectionStats:

    def __init__(self):
        self.stats = defaultdict(lambda: {
            "total": 0,
            "success": 0,
            "failed": 0
        })

    def add_total(self, section):
        self.stats[section]["total"] += 1

    def add_success(self, section):
        self.stats[section]["success"] += 1

    def add_failed(self, section):
        self.stats[section]["failed"] += 1

    def print_summary(self):

        print("\n")
        print("=======================================")
        print("📊 SCRAPER SUMMARY BY SECTION")
        print("=======================================")

        total_all = 0
        success_all = 0
        failed_all = 0

        for section, stat in self.stats.items():

            total = stat["total"]
            success = stat["success"]
            failed = stat["failed"]

            total_all += total
            success_all += success
            failed_all += failed

            print(section)
            print(f"   Total Horses : {total}")
            print(f"   Success      : {success}")
            print(f"   Failed       : {failed}")
            print("")

        print("---------------------------------------")
        print(f"TOTAL HORSES : {total_all}")
        print(f"SUCCESS      : {success_all}")
        print(f"FAILED       : {failed_all}")
        print("=======================================")