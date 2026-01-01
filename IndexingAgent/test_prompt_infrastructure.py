#!/usr/bin/env python3
"""
프롬프트 인프라 단위 테스트

Phase 1에서 구현한 OutputFormatGenerator와 PromptTemplate 테스트
"""

import sys
sys.path.insert(0, '.')

from src.agents.prompts import (
    OutputFormatGenerator,
    generate_output_format,
    PromptTemplate,
    MultiPromptTemplate,
)
from src.agents.models.llm_responses import (
    FileClassificationItem,
    ColumnRoleMapping,
    TableEntityResult,
)


def test_output_format_generator():
    """OutputFormatGenerator 테스트"""
    print("=" * 60)
    print("TEST 1: OutputFormatGenerator")
    print("=" * 60)
    
    generator = OutputFormatGenerator()
    
    # Test 1.1: FileClassificationItem (리스트, wrapper 있음)
    print("\n[1.1] FileClassificationItem (list, wrapper='classifications')")
    format_str = generator.generate(
        item_model=FileClassificationItem,
        wrapper_key="classifications",
        is_list=True
    )
    print(format_str)
    
    # Test 1.2: ColumnRoleMapping (단일 객체, wrapper 없음)
    print("\n[1.2] ColumnRoleMapping (single object, no wrapper)")
    format_str = generator.generate(
        item_model=ColumnRoleMapping,
        wrapper_key=None,
        is_list=False
    )
    print(format_str)
    
    # Test 1.3: 편의 함수
    print("\n[1.3] generate_output_format() 편의 함수")
    format_str = generate_output_format(
        TableEntityResult,
        wrapper_key="tables",
        is_list=True
    )
    print(format_str)
    
    print("\n✅ OutputFormatGenerator 테스트 통과!")
    return True


def test_prompt_template():
    """PromptTemplate 테스트"""
    print("\n" + "=" * 60)
    print("TEST 2: PromptTemplate")
    print("=" * 60)
    
    # 테스트용 프롬프트 클래스 정의
    class TestClassificationPrompt(PromptTemplate):
        name = "test_classification"
        response_model = FileClassificationItem
        response_wrapper_key = "classifications"
        is_list_response = True
        
        system_role = "You are a Medical Data Expert specializing in healthcare informatics."
        
        task_description = """Classify each file as "metadata" or "data":
- metadata: Data dictionaries, codebooks, parameter definitions
- data: Actual measurements, patient records"""
        
        context_template = """[Files to Classify]
{files_info}"""
        
        rules = [
            "Output valid JSON only",
            "Include confidence score for each classification",
        ]
    
    # Test 2.1: build() 테스트
    print("\n[2.1] PromptTemplate.build() 테스트")
    prompt_str = TestClassificationPrompt.build(
        files_info="1. clinical_data.csv (100 rows, 20 columns)\n2. parameters.csv (50 rows, 3 columns)"
    )
    print(prompt_str[:1000] + "..." if len(prompt_str) > 1000 else prompt_str)
    
    # Test 2.2: parse_response() 테스트
    print("\n[2.2] PromptTemplate.parse_response() 테스트")
    mock_response = {
        "classifications": [
            {
                "file_name": "clinical_data.csv",
                "is_metadata": False,
                "confidence": 0.95,
                "reasoning": "Contains patient records"
            },
            {
                "file_name": "parameters.csv",
                "is_metadata": True,
                "confidence": 0.9,
                "reasoning": "Contains parameter definitions"
            }
        ]
    }
    
    items = TestClassificationPrompt.parse_response(mock_response)
    print(f"Parsed {len(items)} items:")
    for item in items:
        print(f"  - {item.file_name}: is_metadata={item.is_metadata}, confidence={item.confidence}")
    
    # Test 2.3: get_info() 테스트
    print("\n[2.3] PromptTemplate.get_info() 테스트")
    info = TestClassificationPrompt.get_info()
    print(info)
    
    print("\n✅ PromptTemplate 테스트 통과!")
    return True


def test_multi_prompt_template():
    """MultiPromptTemplate 테스트"""
    print("\n" + "=" * 60)
    print("TEST 3: MultiPromptTemplate")
    print("=" * 60)
    
    # 개별 프롬프트 정의
    class Task1Prompt(PromptTemplate):
        name = "task1"
        response_model = FileClassificationItem
        response_wrapper_key = "results"
        system_role = "Task 1 Expert"
        task_description = "Do task 1"
        context_template = "{data}"
    
    class Task2Prompt(PromptTemplate):
        name = "task2"
        response_model = TableEntityResult
        response_wrapper_key = "entities"
        system_role = "Task 2 Expert"
        task_description = "Do task 2"
        context_template = "{data}"
    
    # Multi 프롬프트 정의
    class MultiTaskPrompts(MultiPromptTemplate):
        prompts = {
            "task1": Task1Prompt,
            "task2": Task2Prompt,
        }
    
    # Test 3.1: list_tasks()
    print("\n[3.1] MultiPromptTemplate.list_tasks()")
    tasks = MultiTaskPrompts.list_tasks()
    print(f"Available tasks: {tasks}")
    
    # Test 3.2: build_for_task()
    print("\n[3.2] MultiPromptTemplate.build_for_task('task1')")
    prompt_str = MultiTaskPrompts.build_for_task("task1", data="Test data for task 1")
    print(prompt_str[:500] + "..." if len(prompt_str) > 500 else prompt_str)
    
    print("\n✅ MultiPromptTemplate 테스트 통과!")
    return True


def main():
    """모든 테스트 실행"""
    print("\n🧪 프롬프트 인프라 단위 테스트 시작\n")
    
    results = []
    
    try:
        results.append(("OutputFormatGenerator", test_output_format_generator()))
    except Exception as e:
        print(f"❌ OutputFormatGenerator 테스트 실패: {e}")
        results.append(("OutputFormatGenerator", False))
    
    try:
        results.append(("PromptTemplate", test_prompt_template()))
    except Exception as e:
        print(f"❌ PromptTemplate 테스트 실패: {e}")
        results.append(("PromptTemplate", False))
    
    try:
        results.append(("MultiPromptTemplate", test_multi_prompt_template()))
    except Exception as e:
        print(f"❌ MultiPromptTemplate 테스트 실패: {e}")
        results.append(("MultiPromptTemplate", False))
    
    # 결과 요약
    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 모든 테스트 통과!")
    else:
        print("\n⚠️ 일부 테스트 실패")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

