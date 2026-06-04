from src.config import (
    DATA_SOURCE,
    INPUT_LOGS_DIR,
    INPUT_SCREENSHOTS_DIR,
    OUTPUT_MESSAGES_DIR,
    OUTPUT_REPORTS_DIR,
    RUN_LOG_FILE,
    ZABBIX_API_TOKEN,
    ZABBIX_API_URL,
    ZABBIX_VERIFY_SSL,
)
from src.capture.zabbix_graph_capture import run_graph_capture, write_capture_summary
from src.capture.fortigate_capture import run_fortigate_capture
from src.clients.zabbix_client import ZabbixClient
from src.excel.report_generator import save_excel_report
from src.messages.message_builder import build_message
from src.messages.message_service import save_message
from src.messages.report_builder import build_summary
from src.services.report_service import save_report
from src.services.utilization_service import (
    summarize_records,
    sort_site_data,
    get_sites_above_70,
)
from src.sources.txt_source import fetch_txt_records
from src.sources.zabbix_source import fetch_all_site_records_with_stats
from src.utils.date_utils import ask_report_period
from src.utils.logger import setup_logger
from src.validation.accuracy_checker import run_accuracy_checks
from src.validation.report_accuracy_checker import run_report_accuracy_checks


def main() -> None:
    logger = setup_logger(RUN_LOG_FILE)

    try:
        report_period = ask_report_period()
    except ValueError as error:
        print(error)
        return

    logger.info(
        "Daily utilization automation started | "
        f"data source: {DATA_SOURCE} | "
        f"mode: {report_period['mode']} | "
        f"from_date: {report_period['from_date']} | "
        f"to_date: {report_period['to_date']} | "
        f"label: {report_period['label']}"
    )

    try:
        zabbix_stats: list[dict] = []
        file_summaries: list[dict] = []

        if DATA_SOURCE == "zabbix":
            if not ZABBIX_API_URL:
                print("Missing ZABBIX_API_URL in .env")
                return

            if not ZABBIX_API_TOKEN:
                print("Missing ZABBIX_API_TOKEN in .env")
                return

            client = ZabbixClient(
                ZABBIX_API_URL,
                ZABBIX_API_TOKEN,
                verify_ssl=ZABBIX_VERIFY_SSL,
            )

            records, zabbix_stats = fetch_all_site_records_with_stats(
                client,
                from_date=report_period["from_date"],
                to_date=report_period["to_date"],
            )

            logger.info(f"Zabbix records fetched successfully: {len(records)}")

            for item in zabbix_stats:
                logger.info(
                    f"Zabbix fetch stats | {item['site']} | "
                    f"from_date={item['from_date']} | "
                    f"to_date={item['to_date']} | "
                    f"primary_in={item['primary_in_rows']} | "
                    f"primary_out={item['primary_out_rows']} | "
                    f"secondary_in={item['secondary_in_rows']} | "
                    f"secondary_out={item['secondary_out_rows']} | "
                    f"primary_merged={item['primary_merged_rows']} | "
                    f"secondary_merged={item['secondary_merged_rows']} | "
                    f"total_records={item['total_records']}"
                )

        else:
            records, file_summaries = fetch_txt_records(INPUT_LOGS_DIR)

            if not file_summaries:
                logger.warning("No TXT log files found in input/logs")
                print("No TXT log files found in input/logs")
                return

            for item in file_summaries:
                logger.info(f"Processing file: {item['file_name']}")
                logger.info(f"Detected site: {item['site']} | link: {item['link']}")
                logger.info(
                    f"Line stats | total={item['total_lines']} | "
                    f"matched={item['matched_lines']} | "
                    f"unmatched={item['unmatched_lines']} | "
                    f"blank={item['blank_lines']} | "
                    f"ignored={item['ignored_header_lines']} | "
                    f"duplicates={item['duplicate_lines']}"
                )

                effective_non_blank = (
                    item["matched_lines"]
                    + item["unmatched_lines"]
                    + item["ignored_header_lines"]
                    + item["duplicate_lines"]
                )
                logger.info(f"Effective non-blank lines: {effective_non_blank}")

                if item["site"] == "Unknown":
                    logger.warning(f"Unknown site detected from filename: {item['file_name']}")

                if item["link"] == "Unknown":
                    logger.warning(f"Unknown link detected from filename: {item['file_name']}")

                if item["value_count"] == 0:
                    logger.warning(f"No valid utilization values found in file: {item['file_name']}")

                if item["unmatched_lines"] > 0:
                    logger.warning(
                        f"{item['unmatched_lines']} unmatched lines found in file: {item['file_name']}"
                    )
                    for sample in item["sample_unmatched_lines"]:
                        logger.warning(f"Sample unmatched -> {sample}")

        site_data = summarize_records(records)
        site_data = sort_site_data(site_data)

        if DATA_SOURCE == "txt":
            accuracy_errors = run_accuracy_checks(file_summaries, site_data)

            if accuracy_errors:
                logger.warning("TXT accuracy checker found issues:")
                for error in accuracy_errors:
                    logger.warning(error)
            else:
                logger.info("TXT accuracy checker passed successfully")
        else:
            logger.info("TXT accuracy checker skipped for Zabbix mode")

        report_accuracy_errors = run_report_accuracy_checks(site_data)

        if report_accuracy_errors:
            logger.warning("Report accuracy checker found issues:")
            for error in report_accuracy_errors:
                logger.warning(error)
        else:
            logger.info("Report accuracy checker passed successfully")

        if DATA_SOURCE == "zabbix":
            logger.info("Starting Zabbix graph screenshot capture")
            print("\nStarting Zabbix graph screenshot capture...")

            capture_results = run_graph_capture(report_period=report_period["label"])
            write_capture_summary(capture_results)

            success_count = sum(1 for item in capture_results if item["status"] == "SUCCESS")
            failed_count = sum(1 for item in capture_results if item["status"] == "FAILED")

            logger.info(
                f"Graph capture completed | success={success_count} | failed={failed_count}"
            )

            for item in capture_results:
                if item["status"] == "SUCCESS":
                    logger.info(
                        f"Graph capture success | {item['site']} | {item['link']} | {item['path']}"
                    )
                else:
                    logger.warning(
                        f"Graph capture failed | {item['site']} | {item['link']} | {item['error']}"
                    )

            print(f"Graph capture completed. Success: {success_count}, Failed: {failed_count}")
        else:
            logger.info("Graph screenshot capture skipped for TXT mode")

        eligible_sites = get_sites_above_70(site_data)
        logger.info(f"Sites eligible for FortiGate screenshots: {eligible_sites}")
        print(f"\n[INFO] Sites eligible for FortiGate screenshots: {eligible_sites}")

        fortigate_results: list[dict] = []

        if eligible_sites:
            logger.info("Starting FortiGate screenshot capture for eligible sites")
            print("[INFO] Starting FortiGate screenshot capture for eligible sites")

            for site in eligible_sites:
                logger.info(f"Running FortiGate capture for eligible site: {site}")
                print(f"[INFO] Running FortiGate capture for eligible site: {site}")

                try:
                    run_fortigate_capture(
                        headless=True,
                        source_row_indices=[0, 1, 2, 3],
                        site_name=site,
                    )
                    fortigate_results.append(
                        {
                            "site": site,
                            "status": "SUCCESS",
                            "error": "",
                        }
                    )
                    logger.info(f"FortiGate capture succeeded for site: {site}")
                    print(f"[OK] FortiGate capture succeeded for site: {site}")

                except Exception as error:
                    fortigate_results.append(
                        {
                            "site": site,
                            "status": "FAILED",
                            "error": str(error),
                        }
                    )
                    logger.exception(f"FortiGate capture failed for site: {site} | error: {error}")
                    print(f"[WARN] FortiGate capture failed for site: {site} | {error}")

            fg_success = [item["site"] for item in fortigate_results if item["status"] == "SUCCESS"]
            fg_failed = [item for item in fortigate_results if item["status"] == "FAILED"]

            logger.info(
                f"FortiGate screenshot capture completed | "
                f"success_count={len(fg_success)} | failed_count={len(fg_failed)}"
            )

            if fg_success:
                logger.info(f"FortiGate success sites: {fg_success}")
                print(f"[INFO] FortiGate success sites: {fg_success}")

            if fg_failed:
                failed_site_names = [item["site"] for item in fg_failed]
                logger.warning(f"FortiGate failed sites: {failed_site_names}")
                print(f"[WARN] FortiGate failed sites: {failed_site_names}")

                for item in fg_failed:
                    logger.warning(
                        f"FortiGate failure detail | site={item['site']} | error={item['error']}"
                    )
                    print(f"[WARN] {item['site']} -> {item['error']}")

            print("[INFO] FortiGate screenshot capture completed for eligible sites.")
        else:
            logger.info("No sites crossed above 70. Skipping FortiGate screenshot capture.")
            print("[INFO] No sites crossed above 70. Skipping FortiGate screenshot capture.")

        report_text = build_summary(report_period["label"], site_data, len(file_summaries))
        report_file = save_report(OUTPUT_REPORTS_DIR, report_period["label"], report_text)

        message_text = build_message(report_period["label"], site_data)
        message_file = save_message(OUTPUT_MESSAGES_DIR, report_period["label"], message_text)

        excel_file = save_excel_report(
            OUTPUT_REPORTS_DIR,
            report_period["label"],
            site_data,
            INPUT_SCREENSHOTS_DIR,
        )

        logger.info(f"Report generated successfully: {report_file}")
        logger.info(f"Message generated successfully: {message_file}")
        logger.info(f"Excel generated successfully: {excel_file}")

        print("\nReport generated successfully.")
        print(f"Report saved at: {report_file}")
        print(f"Message saved at: {message_file}")
        print(f"Excel saved at: {excel_file}")

    except Exception as error:
        logger.exception(f"Pipeline failed: {error}")
        print(f"Pipeline failed: {error}")


if __name__ == "__main__":
    main()