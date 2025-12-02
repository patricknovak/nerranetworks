#!/usr/bin/env python3
"""
Test script to verify credit usage tracking and file generation for Tesla Shorts Time.
"""

import json
import tempfile
from pathlib import Path
import sys
import os

# Add digests directory to path to import the function
sys.path.insert(0, str(Path(__file__).parent / "digests"))

# Import the save_credit_usage function
from tesla_shorts_time import save_credit_usage

def test_credit_usage_save():
    """Test that credit usage files are saved correctly."""
    print("="*80)
    print("TESTING CREDIT USAGE FILE GENERATION")
    print("="*80)
    
    # Create a temporary directory for testing
    test_dir = Path(tempfile.mkdtemp())
    print(f"Test directory: {test_dir}")
    
    try:
        # Create sample credit usage data matching the structure
        test_credit_usage = {
            "date": "2025-12-01",
            "episode_number": 337,
            "services": {
                "grok_api": {
                    "x_thread_generation": {
                        "prompt_tokens": 2000,
                        "completion_tokens": 1000,
                        "total_tokens": 3000,
                        "estimated_cost_usd": 0.00003
                    },
                    "podcast_script_generation": {
                        "prompt_tokens": 2500,
                        "completion_tokens": 1500,
                        "total_tokens": 4000,
                        "estimated_cost_usd": 0.00004
                    },
                    "total_tokens": 0,  # Will be calculated
                    "total_cost_usd": 0.0  # Will be calculated
                },
                "elevenlabs_api": {
                    "characters": 10000,
                    "estimated_cost_usd": 0.0  # Will be calculated
                },
                "x_api": {
                    "search_calls": 2,
                    "post_calls": 1,
                    "total_calls": 0  # Will be calculated
                }
            },
            "total_estimated_cost_usd": 0.0  # Will be calculated
        }
        
        # Call the save function
        print("\n1. Calling save_credit_usage()...")
        save_credit_usage(test_credit_usage, test_dir)
        
        # Check if file was created
        expected_filename = f"credit_usage_{test_credit_usage['date']}_ep{test_credit_usage['episode_number']:03d}.json"
        expected_filepath = test_dir / expected_filename
        
        print(f"\n2. Checking if file was created: {expected_filepath}")
        if not expected_filepath.exists():
            print(f"❌ FAILED: File was not created at {expected_filepath}")
            return False
        else:
            print(f"✅ SUCCESS: File exists at {expected_filepath}")
        
        # Read and verify file contents
        print(f"\n3. Reading and verifying file contents...")
        with open(expected_filepath, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        # Verify structure
        required_keys = ['date', 'episode_number', 'services', 'total_estimated_cost_usd']
        for key in required_keys:
            if key not in saved_data:
                print(f"❌ FAILED: Missing required key: {key}")
                return False
            else:
                print(f"   ✅ Key '{key}' present")
        
        # Verify services structure
        required_services = ['grok_api', 'elevenlabs_api', 'x_api']
        for service in required_services:
            if service not in saved_data['services']:
                print(f"❌ FAILED: Missing service: {service}")
                return False
            else:
                print(f"   ✅ Service '{service}' present")
        
        # Verify calculations were performed
        print(f"\n4. Verifying calculations...")
        
        # Check Grok totals
        grok_total = saved_data['services']['grok_api']['total_tokens']
        expected_grok_total = 3000 + 4000  # x_thread + podcast_script
        if grok_total != expected_grok_total:
            print(f"❌ FAILED: Grok total tokens incorrect. Expected {expected_grok_total}, got {grok_total}")
            return False
        else:
            print(f"   ✅ Grok total tokens: {grok_total}")
        
        # Check ElevenLabs cost (should be ~$3.00 for 10000 characters)
        elevenlabs_cost = saved_data['services']['elevenlabs_api']['estimated_cost_usd']
        expected_cost = (10000 / 1000) * 0.30  # $0.30 per 1000 characters
        if abs(elevenlabs_cost - expected_cost) > 0.01:
            print(f"❌ FAILED: ElevenLabs cost incorrect. Expected ~${expected_cost:.2f}, got ${elevenlabs_cost:.2f}")
            return False
        else:
            print(f"   ✅ ElevenLabs cost: ${elevenlabs_cost:.2f}")
        
        # Check X API total calls
        x_total = saved_data['services']['x_api']['total_calls']
        expected_x_total = 2 + 1  # search + post
        if x_total != expected_x_total:
            print(f"❌ FAILED: X API total calls incorrect. Expected {expected_x_total}, got {x_total}")
            return False
        else:
            print(f"   ✅ X API total calls: {x_total}")
        
        # Check total cost
        total_cost = saved_data['total_estimated_cost_usd']
        if total_cost <= 0:
            print(f"❌ FAILED: Total cost should be > 0, got ${total_cost:.4f}")
            return False
        else:
            print(f"   ✅ Total estimated cost: ${total_cost:.4f}")
        
        # Print file contents for verification
        print(f"\n5. File contents:")
        print(json.dumps(saved_data, indent=2))
        
        print(f"\n✅ ALL TESTS PASSED!")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        print(f"\n6. Cleaning up test directory...")
        try:
            import shutil
            shutil.rmtree(test_dir)
            print(f"   ✅ Test directory removed: {test_dir}")
        except Exception as e:
            print(f"   ⚠️  Warning: Could not remove test directory: {e}")

def test_real_digests_directory():
    """Test that we can write to the actual digests directory."""
    print("\n" + "="*80)
    print("TESTING WRITE PERMISSIONS TO DIGESTS DIRECTORY")
    print("="*80)
    
    digests_dir = Path(__file__).parent / "digests"
    
    if not digests_dir.exists():
        print(f"❌ FAILED: digests directory does not exist: {digests_dir}")
        return False
    
    print(f"Digests directory: {digests_dir}")
    print(f"Directory exists: ✅")
    print(f"Directory is writable: {os.access(digests_dir, os.W_OK)}")
    
    # Try to create a test file
    test_file = digests_dir / "test_write_permissions.json"
    try:
        test_file.write_text('{"test": true}')
        print(f"✅ Can write to digests directory")
        test_file.unlink()
        print(f"✅ Can delete files from digests directory")
        return True
    except Exception as e:
        print(f"❌ FAILED: Cannot write to digests directory: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "="*80)
    print("TESLA SHORTS TIME - CREDIT USAGE TEST SUITE")
    print("="*80)
    
    # Test 1: Function works correctly
    test1_passed = test_credit_usage_save()
    
    # Test 2: Can write to actual directory
    test2_passed = test_real_digests_directory()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Test 1 (Function): {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Test 2 (Directory): {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n⚠️  SOME TESTS FAILED")
        sys.exit(1)

