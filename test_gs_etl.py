from mock_generator import MockDataGenerator
from gs_etl import GSheetETL
from looker_manager import LookerAssetManager
import settings as s


if __name__ == "__main__":
    try:
        # 1. GENERATE (Creates data + Applies Formatting immediately)
        gen = MockDataGenerator(s.GEN_CONFIG).generate_test_environment(mode='overwrite') 

        # 2. RUN ETL (Syncs data + Re-applies Formatting)
        GSheetETL(s.ETL_CONFIG).run_etl(overwrite=1)
        #Each run represents a month.
        
        # 3. Update images on looker (Syncs data + Re-applies Formatting)
        # Only runs if GCS_BUCKET_NAME is configured in .env
        if s.LOOKER_CONFIG.get('bucket_name'):
            LookerAssetManager(s.LOOKER_CONFIG).run_update()
        else:
            print("\n⚠️  LOOKER SKIPPED: Code is ready, but Google Cloud Storage requires")
            print("   billing activation (credit card). Feature skipped for now.")
        
        print("\n✅ ALL TASKS COMPLETE")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")