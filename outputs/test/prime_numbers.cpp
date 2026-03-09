#include <iostream>
#include <vector>
#include <cmath>
#include <algorithm>

// 算法1：埃拉托斯特尼筛法（Sieve of Eratosthenes）
std::vector<int> sieveOfEratosthenes(int limit) {
    std::vector<bool> isPrime(limit + 1, true);
    std::vector<int> primes;
    
    isPrime[0] = isPrime[1] = false;
    
    for (int i = 2; i * i <= limit; i++) {
        if (isPrime[i]) {
            for (int j = i * i; j <= limit; j += i) {
                isPrime[j] = false;
            }
        }
    }
    
    for (int i = 2; i <= limit; i++) {
        if (isPrime[i]) {
            primes.push_back(i);
        }
    }
    
    return primes;
}

// 算法2：试除法（Trial Division）
std::vector<int> trialDivision(int limit) {
    std::vector<int> primes;
    
    for (int num = 2; num <= limit; num++) {
        bool isPrime = true;
        
        // 优化：只需要检查到sqrt(num)
        int sqrtNum = static_cast<int>(std::sqrt(num));
        for (int i = 2; i <= sqrtNum; i++) {
            if (num % i == 0) {
                isPrime = false;
                break;
            }
        }
        
        if (isPrime) {
            primes.push_back(num);
        }
    }
    
    return primes;
}

// 算法3：优化的试除法（跳过偶数）
std::vector<int> optimizedTrialDivision(int limit) {
    std::vector<int> primes;
    
    if (limit >= 2) {
        primes.push_back(2); // 2是唯一的偶质数
    }
    
    // 只检查奇数
    for (int num = 3; num <= limit; num += 2) {
        bool isPrime = true;
        int sqrtNum = static_cast<int>(std::sqrt(num));
        
        // 只用质数来试除
        for (int prime : primes) {
            if (prime > sqrtNum) break;
            if (num % prime == 0) {
                isPrime = false;
                break;
            }
        }
        
        if (isPrime) {
            primes.push_back(num);
        }
    }
    
    return primes;
}

// 辅助函数：打印质数
void printPrimes(const std::vector<int>& primes, const std::string& algorithmName) {
    std::cout << algorithmName << " 找到的质数 (" << primes.size() << "个): ";
    for (size_t i = 0; i < primes.size(); i++) {
        std::cout << primes[i];
        if (i < primes.size() - 1) {
            std::cout << ", ";
        }
        // 每行显示10个数字
        if ((i + 1) % 10 == 0 && i < primes.size() - 1) {
            std::cout << "\n                    ";
        }
    }
    std::cout << std::endl << std::endl;
}

// 比较两个向量是否相等
bool compareVectors(const std::vector<int>& v1, const std::vector<int>& v2) {
    if (v1.size() != v2.size()) return false;
    for (size_t i = 0; i < v1.size(); i++) {
        if (v1[i] != v2[i]) return false;
    }
    return true;
}

int main() {
    const int LIMIT = 100;
    
    std::cout << "=== 求解100以内质数的不同算法 ===" << std::endl;
    std::cout << "上限: " << LIMIT << std::endl << std::endl;
    
    // 使用算法1：埃拉托斯特尼筛法
    std::vector<int> primes1 = sieveOfEratosthenes(LIMIT);
    printPrimes(primes1, "算法1: 埃拉托斯特尼筛法");
    
    // 使用算法2：试除法
    std::vector<int> primes2 = trialDivision(LIMIT);
    printPrimes(primes2, "算法2: 试除法");
    
    // 使用算法3：优化的试除法
    std::vector<int> primes3 = optimizedTrialDivision(LIMIT);
    printPrimes(primes3, "算法3: 优化的试除法（跳过偶数）");
    
    // 验证算法结果是否一致
    std::cout << "=== 算法验证 ===" << std::endl;
    bool allMatch = compareVectors(primes1, primes2) && compareVectors(primes1, primes3);
    
    if (allMatch) {
        std::cout << "✓ 所有算法结果一致！" << std::endl;
    } else {
        std::cout << "✗ 算法结果不一致！" << std::endl;
    }
    
    // 算法性能分析
    std::cout << std::endl << "=== 算法复杂度分析 ===" << std::endl;
    std::cout << "1. 埃拉托斯特尼筛法: O(n log log n)" << std::endl;
    std::cout << "2. 试除法: O(n√n)" << std::endl;
    std::cout << "3. 优化的试除法: O(n√n / log n)" << std::endl;
    
    return 0;
}